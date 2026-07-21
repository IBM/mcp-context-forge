import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { serversApi } from "@/api/servers";
import { useMCPServerForm } from "./useMCPServerForm";

describe("useMCPServerForm", () => {
  describe("Initial State", () => {
    it("should initialize with default values", () => {
      const { result } = renderHook(() => useMCPServerForm());

      expect(result.current.name).toBe("");
      expect(result.current.url).toBe("");
      expect(result.current.description).toBe("");
      expect(result.current.transport).toBe("STREAMABLEHTTP");
      expect(result.current.advancedOpen).toBe(false);
      expect(result.current.visibility).toBe("public");
      expect(result.current.teamId).toBe("");
      expect(result.current.authType).toBe("none");
      expect(result.current.oneTimeAuth).toBe(false);
      expect(result.current.passthroughHeaders).toBe("");
      expect(result.current.authUsername).toBe("");
      expect(result.current.authPassword).toBe("");
      expect(result.current.errors).toEqual({});
      expect(result.current.isValid).toBe(false);
    });
  });

  describe("State Updates", () => {
    it("should update transport type", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setTransport("SSE");
      });

      expect(result.current.transport).toBe("SSE");
    });

    it("should update name", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
      });

      expect(result.current.name).toBe("Test Server");
    });

    it("should update url", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setUrl("http://localhost:3000");
      });

      expect(result.current.url).toBe("http://localhost:3000");
    });

    it("should update description", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setDescription("Test description");
      });

      expect(result.current.description).toBe("Test description");
    });

    it("should update teamId", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setTeamId("team-xyz-456");
      });

      expect(result.current.teamId).toBe("team-xyz-456");
    });

    it("should toggle advanced settings", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setAdvancedOpen(true);
      });

      expect(result.current.advancedOpen).toBe(true);

      act(() => {
        result.current.setAdvancedOpen((prev) => !prev);
      });

      expect(result.current.advancedOpen).toBe(false);
    });

    it("should update visibility", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setVisibility("team");
      });

      expect(result.current.visibility).toBe("team");
    });

    it("should update auth setters", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setAuthType("basic");
        result.current.setAuthUsername("user");
        result.current.setAuthPassword("pass");
        result.current.setAuthToken("token");
        result.current.setOneTimeAuth(true);
        result.current.setPassthroughHeaders("Authorization");
        result.current.setCaCertificate("cert");
        result.current.setBearerToken("bearer");
        result.current.setCustomHeaders([{ id: "1", key: "x", value: "y" }]);
        result.current.setOAuthClientId("id");
        result.current.setOAuthClientSecret("secret");
        result.current.setOAuthTokenUrl("url");
        result.current.setOAuthGrantType("password");
        result.current.setOAuthIssuerUrl("issuer");
        result.current.setOAuthRedirectUri("redirect");
        result.current.setOAuthAuthorizationUrl("auth");
        result.current.setOAuthScopes("scope");
        result.current.setOAuthStoreTokens(false);
        result.current.setOAuthAutoRefresh(false);
        result.current.setOAuthUsername("o_user");
        result.current.setOAuthPassword("o_pass");
        result.current.setQueryParamName("param");
        result.current.setQueryParamApiKey("key");
      });

      expect(result.current.authType).toBe("basic");
      expect(result.current.authUsername).toBe("user");
      expect(result.current.authPassword).toBe("pass");
      expect(result.current.authToken).toBe("token");
      expect(result.current.oneTimeAuth).toBe(true);
      expect(result.current.passthroughHeaders).toBe("Authorization");
      expect(result.current.caCertificate).toBe("cert");
      expect(result.current.bearerToken).toBe("bearer");
      expect(result.current.customHeaders).toEqual([{ id: "1", key: "x", value: "y" }]);
      expect(result.current.oauthClientId).toBe("id");
      expect(result.current.oauthClientSecret).toBe("secret");
      expect(result.current.oauthTokenUrl).toBe("url");
      expect(result.current.oauthGrantType).toBe("password");
      expect(result.current.oauthIssuerUrl).toBe("issuer");
      expect(result.current.oauthRedirectUri).toBe("redirect");
      expect(result.current.oauthAuthorizationUrl).toBe("auth");
      expect(result.current.oauthScopes).toBe("scope");
      expect(result.current.oauthStoreTokens).toBe(false);
      expect(result.current.oauthAutoRefresh).toBe(false);
      expect(result.current.oauthUsername).toBe("o_user");
      expect(result.current.oauthPassword).toBe("o_pass");
      expect(result.current.queryParamName).toBe("param");
      expect(result.current.queryParamApiKey).toBe("key");
    });
  });

  describe("Form Validation", () => {
    it("should validate required fields", () => {
      const { result } = renderHook(() => useMCPServerForm());

      let isValid: boolean;
      act(() => {
        isValid = result.current.validateForm();
      });

      expect(isValid!).toBe(false);
      expect(result.current.errors.name).toBeDefined();
      expect(result.current.errors.url).toBeDefined();
    });

    it("should validate URL format", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("invalid-url");
      });

      act(() => {
        result.current.validateForm();
      });

      expect(result.current.errors.url).toBe("URL must start with http:// or https://");
    });

    it("should add teamId error when visibility is team and teamId is empty", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setVisibility("team");
      });

      act(() => {
        result.current.validateForm();
      });

      expect(result.current.errors.teamId).toBeDefined();
    });

    it("should pass validation when visibility is team and teamId is set", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setVisibility("team");
        result.current.setTeamId("team-abc");
      });

      let isValid: boolean;
      act(() => {
        isValid = result.current.validateForm();
      });

      expect(isValid!).toBe(true);
      expect(result.current.errors.teamId).toBeUndefined();
    });

    it("should pass validation with valid data", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
      });

      let isValid: boolean;
      act(() => {
        isValid = result.current.validateForm();
      });

      expect(isValid!).toBe(true);
      expect(result.current.errors).toEqual({});
    });

    it("should validate name length with sanitization", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("a".repeat(101));
        result.current.setUrl("http://localhost:3000");
      });

      act(() => {
        result.current.validateForm();
      });

      // Sanitization happens during Zod validation (.parse()), truncating to 100 chars
      // So validation passes (no error) - the Zod transform sanitizes before validation
      expect(result.current.errors.name).toBeUndefined();
      // Note: State still holds original 101 chars; sanitization only in Zod schema
      expect(result.current.name.length).toBe(101);
    });

    it("should validate description length with sanitization", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setDescription("a".repeat(501));
      });

      act(() => {
        result.current.validateForm();
      });

      // Sanitization happens during Zod validation (.parse()), truncating to 500 chars
      // So validation passes (no error) - the Zod transform sanitizes before validation
      expect(result.current.errors.description).toBeUndefined();
      // Note: State still holds original 501 chars; sanitization only in Zod schema
      expect(result.current.description.length).toBe(501);
    });
  });

  describe("Form Submission", () => {
    it("should not submit with invalid data", () => {
      const { result } = renderHook(() => useMCPServerForm());
      const mockEvent = {
        preventDefault: () => {},
      } as React.FormEvent<HTMLFormElement>;

      act(() => {
        result.current.handleSubmit(mockEvent);
      });

      expect(result.current.errors.name).toBeDefined();
      expect(result.current.errors.url).toBeDefined();
    });

    it("should submit with valid data and call success callback", async () => {
      const { result } = renderHook(() => useMCPServerForm());
      const mockEvent = {
        preventDefault: () => {},
      } as React.FormEvent<HTMLFormElement>;
      let callbackCalled = false;

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
      });

      await act(async () => {
        await result.current.handleSubmit(mockEvent, () => {
          callbackCalled = true;
        });
      });

      await waitFor(() => {
        expect(callbackCalled).toBe(true);
      });

      expect(result.current.errors).toEqual({});
    });

    it("should reset form after successful submission", async () => {
      const { result } = renderHook(() => useMCPServerForm());
      const mockEvent = {
        preventDefault: () => {},
      } as React.FormEvent<HTMLFormElement>;

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setDescription("Test description");
      });

      await act(async () => {
        await result.current.handleSubmit(mockEvent);
      });

      await waitFor(() => {
        expect(result.current.name).toBe("");
      });

      expect(result.current.url).toBe("");
      expect(result.current.description).toBe("");
    });
  });

  describe("Form Reset", () => {
    it("should reset all fields to initial state", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setTransport("SSE");
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setDescription("Test description");
        result.current.setAdvancedOpen(true);
        result.current.setVisibility("private");
        result.current.setAuthType("basic");
      });

      act(() => {
        result.current.resetForm();
      });

      expect(result.current.transport).toBe("STREAMABLEHTTP");
      expect(result.current.name).toBe("");
      expect(result.current.url).toBe("");
      expect(result.current.description).toBe("");
      expect(result.current.advancedOpen).toBe(false);
      expect(result.current.visibility).toBe("public");
      expect(result.current.teamId).toBe("");
      expect(result.current.authType).toBe("none");
      expect(result.current.errors).toEqual({});
    });
  });

  describe("isValid Property", () => {
    it("should be false when name is empty", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setUrl("http://localhost:3000");
      });

      expect(result.current.isValid).toBe(false);
    });

    it("should be false when url is empty", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
      });

      expect(result.current.isValid).toBe(false);
    });

    it("should be true when both name and url are provided", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
      });

      expect(result.current.isValid).toBe(true);
    });

    it("should be false when visibility is team but teamId is empty", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setVisibility("team");
      });

      expect(result.current.isValid).toBe(false);
    });

    it("should be true when visibility is team and teamId is provided", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setVisibility("team");
        result.current.setTeamId("team-abc");
      });

      expect(result.current.isValid).toBe(true);
    });
  });

  describe("getFormData", () => {
    it("should return current form data", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setDescription("Test description");
      });

      const formData = result.current.getFormData();

      expect(formData.name).toBe("Test Server");
      expect(formData.url).toBe("http://localhost:3000");
      expect(formData.description).toBe("Test description");
      expect(formData.transport).toBe("STREAMABLEHTTP");
      expect(formData.visibility).toBe("public");
    });

    it("includes teamId when visibility is team", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setVisibility("team");
        result.current.setTeamId("team-abc-123");
      });

      const formData = result.current.getFormData();
      expect(formData.teamId).toBe("team-abc-123");
    });

    it("omits teamId when visibility is not team", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setVisibility("private");
        result.current.setTeamId("team-abc-123");
      });

      const formData = result.current.getFormData();
      expect(formData.teamId).toBeUndefined();
    });
  });

  describe("getFormData - Auth Type Mapping", () => {
    it('sends authType "" when auth type is "none" to clear existing auth', () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("none");
      });

      expect(result.current.getFormData().authType).toBe("");
    });

    it('maps "custom" to "authheaders" for the API', () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("custom");
        result.current.setCustomHeaders([{ id: "1", key: "X-API-Key", value: "secret" }]);
      });

      expect(result.current.getFormData().authType).toBe("authheaders");
    });

    it('maps "query" to "query_param" for the API', () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("query");
        result.current.setQueryParamName("api_key");
        result.current.setQueryParamApiKey("secret");
      });

      expect(result.current.getFormData().authType).toBe("query_param");
    });

    it('passes "basic", "bearer", and "oauth" auth types through unchanged', () => {
      const { result } = renderHook(() => useMCPServerForm());

      for (const type of ["basic", "bearer", "oauth"] as const) {
        act(() => {
          result.current.setAuthType(type);
        });
        expect(result.current.getFormData().authType).toBe(type);
      }
    });
  });

  describe("getFormData - authToken scoping", () => {
    it("includes authToken when authType is bearer and token is set", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("bearer");
        result.current.setBearerToken("real-token-abc123");
      });

      expect(result.current.getFormData().authToken).toBe("real-token-abc123");
    });

    it("includes authToken when bearer token looks like a masked placeholder", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("bearer");
        result.current.setBearerToken("*****");
      });

      expect(result.current.getFormData().authToken).toBe("*****");
    });

    it("omits authToken when authType is bearer but token is empty", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("bearer");
        result.current.setBearerToken("");
      });

      expect(result.current.getFormData().authToken).toBeUndefined();
    });

    it("omits authToken when authType is basic (not bearer)", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("basic");
        result.current.setAuthUsername("admin");
        result.current.setAuthPassword("pass");
        result.current.setBearerToken("should-be-excluded");
      });

      expect(result.current.getFormData().authToken).toBeUndefined();
    });

    it("omits authToken when authType is none", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("none");
        result.current.setBearerToken("should-be-excluded");
      });

      expect(result.current.getFormData().authToken).toBeUndefined();
    });
  });

  describe("getFormData - authPassword scoping", () => {
    it("includes authPassword when authType is basic and password is set", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("basic");
        result.current.setAuthUsername("admin");
        result.current.setAuthPassword("real-pass");
      });

      expect(result.current.getFormData().authPassword).toBe("real-pass");
    });

    it("includes authPassword when it looks like a masked placeholder", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("basic");
        result.current.setAuthUsername("admin");
        result.current.setAuthPassword("*****");
      });

      expect(result.current.getFormData().authPassword).toBe("*****");
    });

    it("omits authPassword when authType is basic but password is empty", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("basic");
        result.current.setAuthUsername("admin");
        result.current.setAuthPassword("");
      });

      expect(result.current.getFormData().authPassword).toBeUndefined();
    });

    it("omits authPassword when authType is bearer (not basic)", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("bearer");
        result.current.setBearerToken("my-token");
        result.current.setAuthPassword("should-be-excluded");
      });

      expect(result.current.getFormData().authPassword).toBeUndefined();
    });

    it("omits authPassword when authType is oauth (not basic)", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("oauth");
        result.current.setOAuthGrantType("client_credentials");
        result.current.setAuthPassword("should-be-excluded");
      });

      expect(result.current.getFormData().authPassword).toBeUndefined();
    });
  });

  describe("getFormData - Custom Headers", () => {
    it("sends auth_headers array for custom auth type", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("custom");
        result.current.setCustomHeaders([
          { id: "1", key: "X-API-Key", value: "secret" },
          { id: "2", key: "X-Tenant", value: "acme" },
        ]);
      });

      expect(result.current.getFormData().auth_headers).toEqual([
        { key: "X-API-Key", value: "secret" },
        { key: "X-Tenant", value: "acme" },
      ]);
    });

    it("excludes headers without keys", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("custom");
        result.current.setCustomHeaders([
          { id: "1", key: "X-API-Key", value: "secret" },
          { id: "2", key: "", value: "orphan" },
        ]);
      });

      expect(result.current.getFormData().auth_headers).toEqual([
        { key: "X-API-Key", value: "secret" },
      ]);
    });

    it("sends remaining headers when one is removed", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("custom");
        result.current.setCustomHeaders([
          { id: "1", key: "X-First", value: "one" },
          { id: "2", key: "X-Second", value: "two" },
          { id: "3", key: "X-Third", value: "three" },
        ]);
      });

      act(() => {
        result.current.setCustomHeaders([
          { id: "1", key: "X-First", value: "one" },
          { id: "3", key: "X-Third", value: "three" },
        ]);
      });

      expect(result.current.getFormData().auth_headers).toEqual([
        { key: "X-First", value: "one" },
        { key: "X-Third", value: "three" },
      ]);
    });

    it("returns undefined auth_headers when auth type is not custom", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("basic");
        result.current.setCustomHeaders([{ id: "1", key: "X-API-Key", value: "secret" }]);
      });

      expect(result.current.getFormData().auth_headers).toBeUndefined();
    });
  });

  describe("getFormData - Query Parameter Auth", () => {
    it("sends snake_case auth_query_param fields with query_param auth type", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("query");
        result.current.setQueryParamName("api_key");
        result.current.setQueryParamApiKey("my-secret");
      });

      const data = result.current.getFormData();
      expect(data.authType).toBe("query_param");
      expect(data.auth_query_param_key).toBe("api_key");
      expect(data.auth_query_param_value).toBe("my-secret");
    });

    it("omits query param fields when auth type is not query", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("basic");
        result.current.setQueryParamName("api_key");
        result.current.setQueryParamApiKey("secret");
      });

      const data = result.current.getFormData();
      expect(data.auth_query_param_key).toBeUndefined();
      expect(data.auth_query_param_value).toBeUndefined();
    });
  });

  describe("getFormData - OAuth Config", () => {
    it("includes store_tokens and auto_refresh in oauth_config", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("oauth");
        result.current.setOAuthGrantType("client_credentials");
        result.current.setOAuthStoreTokens(true);
        result.current.setOAuthAutoRefresh(false);
      });

      const config = result.current.getFormData().oauth_config;
      expect(config?.store_tokens).toBe(true);
      expect(config?.auto_refresh).toBe(false);
    });

    it("sends client_credentials fields without auth/redirect URLs", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("oauth");
        result.current.setOAuthGrantType("client_credentials");
        result.current.setOAuthClientId("client-id");
        result.current.setOAuthTokenUrl("https://auth.example.com/token");
      });

      const config = result.current.getFormData().oauth_config;
      expect(config?.grant_type).toBe("client_credentials");
      expect(config?.client_id).toBe("client-id");
      expect(config?.token_url).toBe("https://auth.example.com/token");
      expect(config?.authorization_url).toBeUndefined();
      expect(config?.redirect_uri).toBeUndefined();
    });

    it("sends authorization_code fields including auth and redirect URLs", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("oauth");
        result.current.setOAuthGrantType("authorization_code");
        result.current.setOAuthTokenUrl("https://auth.example.com/token");
        result.current.setOAuthAuthorizationUrl("https://auth.example.com/authorize");
        result.current.setOAuthRedirectUri("https://gateway.example.com/callback");
      });

      const config = result.current.getFormData().oauth_config;
      expect(config?.grant_type).toBe("authorization_code");
      expect(config?.authorization_url).toBe("https://auth.example.com/authorize");
      expect(config?.redirect_uri).toBe("https://gateway.example.com/callback");
    });

    it("sends password grant type with username and password, no auth/redirect URLs", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("oauth");
        result.current.setOAuthGrantType("password");
        result.current.setOAuthUsername("service-account");
        result.current.setOAuthPassword("svc-pass");
      });

      const config = result.current.getFormData().oauth_config;
      expect(config?.grant_type).toBe("password");
      expect(config?.username).toBe("service-account");
      expect(config?.password).toBe("svc-pass");
      expect(config?.authorization_url).toBeUndefined();
      expect(config?.redirect_uri).toBeUndefined();
    });

    it("returns undefined oauth_config when auth type is not oauth", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("Test Server");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("basic");
      });

      expect(result.current.getFormData().oauth_config).toBeUndefined();
    });
  });

  describe("Edit Mode - Form Population from API", () => {
    it("maps 'authheaders' from API response to 'custom' auth type", async () => {
      server.use(
        http.get("/gateways/gw-1", () =>
          HttpResponse.json({
            name: "My Server",
            url: "http://localhost:3000",
            authType: "authheaders",
            authHeaders: [{ key: "X-API-Key", value: "*****" }],
          }),
        ),
      );

      const { result } = renderHook(() => useMCPServerForm("gw-1"));

      await waitFor(() => expect(result.current.authType).toBe("custom"));
    });

    it("maps 'query_param' from API response to 'query' auth type", async () => {
      server.use(
        http.get("/gateways/gw-2", () =>
          HttpResponse.json({
            name: "My Server",
            url: "http://localhost:3000",
            authType: "query_param",
            authQueryParamKey: "api_key",
            authQueryParamValueMasked: "*****",
          }),
        ),
      );

      const { result } = renderHook(() => useMCPServerForm("gw-2"));

      await waitFor(() => expect(result.current.authType).toBe("query"));
      expect(result.current.queryParamName).toBe("api_key");
      expect(result.current.queryParamApiKey).toBe("*****");
    });

    it("populates advanced settings and OAuth config from the API", async () => {
      server.use(
        http.get("/gateways/gw-adv", () =>
          HttpResponse.json({
            name: "Advanced Server",
            url: "http://localhost:3000",
            transport: "STREAMABLEHTTP",
            passthroughHeaders: ["X-Trace", "X-Env"],
            oneTimeAuth: true,
            caCertificate: "-----BEGIN CERTIFICATE-----",
            oauthConfig: {
              grant_type: "authorization_code",
              client_id: "client-123",
              client_secret: "secret-xyz", // pragma: allowlist secret
              token_url: "https://auth.example.com/token",
              issuer: "https://auth.example.com",
              redirect_uri: "https://app.example.com/callback",
              authorization_url: "https://auth.example.com/authorize",
              scopes: ["read", "write"],
              username: "oauth-user",
              password: "oauth-pass", // pragma: allowlist secret
              store_tokens: true,
            },
          }),
        ),
      );

      const { result } = renderHook(() => useMCPServerForm("gw-adv"));

      await waitFor(() => expect(result.current.passthroughHeaders).toBe("X-Trace, X-Env"));
      expect(result.current.oneTimeAuth).toBe(true);
      expect(result.current.caCertificate).toBe("-----BEGIN CERTIFICATE-----");
      expect(result.current.oauthGrantType).toBe("authorization_code");
      expect(result.current.oauthClientId).toBe("client-123");
      expect(result.current.oauthTokenUrl).toBe("https://auth.example.com/token");
      expect(result.current.oauthIssuerUrl).toBe("https://auth.example.com");
      expect(result.current.oauthScopes).toBe("read write");
      expect(result.current.oauthStoreTokens).toBe(true);
      expect(result.current.oauthUsername).toBe("oauth-user");
    });

    it("accepts OAuth scopes provided as a plain string", async () => {
      server.use(
        http.get("/gateways/gw-scopes", () =>
          HttpResponse.json({
            name: "Scopes Server",
            url: "http://localhost:3000",
            oauthConfig: { grant_type: "client_credentials", scopes: "read write admin" },
          }),
        ),
      );

      const { result } = renderHook(() => useMCPServerForm("gw-scopes"));

      await waitFor(() => expect(result.current.oauthScopes).toBe("read write admin"));
    });

    it("populates basic auth username and masked password from API", async () => {
      server.use(
        http.get("/gateways/gw-3", () =>
          HttpResponse.json({
            name: "My Server",
            url: "http://localhost:3000",
            authType: "basic",
            authUsername: "admin",
            authPassword: "*****", // pragma: allowlist secret
          }),
        ),
      );

      const { result } = renderHook(() => useMCPServerForm("gw-3"));

      await waitFor(() => expect(result.current.authType).toBe("basic"));
      expect(result.current.authUsername).toBe("admin");
      expect(result.current.authPassword).toBe("*****");
    });

    it("populates bearer token from API response", async () => {
      server.use(
        http.get("/gateways/gw-4", () =>
          HttpResponse.json({
            name: "My Server",
            url: "http://localhost:3000",
            authType: "bearer",
            authToken: "*****",
          }),
        ),
      );

      const { result } = renderHook(() => useMCPServerForm("gw-4"));

      await waitFor(() => expect(result.current.authType).toBe("bearer"));
      expect(result.current.bearerToken).toBe("*****");
    });

    it("populates multiple custom headers from API response", async () => {
      server.use(
        http.get("/gateways/gw-5", () =>
          HttpResponse.json({
            name: "My Server",
            url: "http://localhost:3000",
            authType: "authheaders",
            authHeaders: [
              { key: "X-API-Key", value: "*****" },
              { key: "X-Tenant", value: "*****" },
            ],
          }),
        ),
      );

      const { result } = renderHook(() => useMCPServerForm("gw-5"));

      await waitFor(() => expect(result.current.customHeaders).toHaveLength(2));
      expect(result.current.customHeaders[0].key).toBe("X-API-Key");
      expect(result.current.customHeaders[1].key).toBe("X-Tenant");
    });

    it("populates oauth store_tokens and auto_refresh as true from API", async () => {
      server.use(
        http.get("/gateways/gw-6", () =>
          HttpResponse.json({
            name: "My Server",
            url: "http://localhost:3000",
            authType: "oauth",
            oauthConfig: {
              grant_type: "client_credentials",
              store_tokens: true,
              auto_refresh: true,
            },
          }),
        ),
      );

      const { result } = renderHook(() => useMCPServerForm("gw-6"));

      await waitFor(() => expect(result.current.authType).toBe("oauth"));
      expect(result.current.oauthStoreTokens).toBe(true);
      expect(result.current.oauthAutoRefresh).toBe(true);
    });

    it("populates oauth store_tokens and auto_refresh as false from API", async () => {
      server.use(
        http.get("/gateways/gw-7", () =>
          HttpResponse.json({
            name: "My Server",
            url: "http://localhost:3000",
            authType: "oauth",
            oauthConfig: {
              grant_type: "client_credentials",
              store_tokens: false,
              auto_refresh: false,
            },
          }),
        ),
      );

      const { result } = renderHook(() => useMCPServerForm("gw-7"));

      await waitFor(() => expect(result.current.authType).toBe("oauth"));
      expect(result.current.oauthStoreTokens).toBe(false);
      expect(result.current.oauthAutoRefresh).toBe(false);
    });

    it("defaults oauth store_tokens and auto_refresh to false when absent from API response", async () => {
      server.use(
        http.get("/gateways/gw-8", () =>
          HttpResponse.json({
            name: "My Server",
            url: "http://localhost:3000",
            authType: "oauth",
            oauthConfig: { grant_type: "client_credentials" },
          }),
        ),
      );

      const { result } = renderHook(() => useMCPServerForm("gw-8"));

      await waitFor(() => expect(result.current.authType).toBe("oauth"));
      expect(result.current.oauthStoreTokens).toBe(false);
      expect(result.current.oauthAutoRefresh).toBe(false);
    });

    it("opens the advanced panel when server has auth configured", async () => {
      server.use(
        http.get("/gateways/gw-9", () =>
          HttpResponse.json({
            name: "My Server",
            url: "http://localhost:3000",
            authType: "bearer",
            authToken: "*****",
          }),
        ),
      );

      const { result } = renderHook(() => useMCPServerForm("gw-9"));

      await waitFor(() => expect(result.current.advancedOpen).toBe(true));
    });

    describe("OAuth Authorization Flow", () => {
      it("should initialize oauthPending as false", () => {
        const { result } = renderHook(() => useMCPServerForm());

        expect(result.current.oauthPending).toBe(false);
        expect(result.current.oauthNotification).toBeNull();
      });

      it("should expose clearOAuthNotification function", () => {
        const { result } = renderHook(() => useMCPServerForm());

        expect(typeof result.current.clearOAuthNotification).toBe("function");
      });

      it("should trigger OAuth authorization after successful gateway creation with OAuth auth type", async () => {
        server.use(
          http.post("/gateways", () => {
            return HttpResponse.json({
              id: "new-gateway-123",
              name: "Test OAuth Gateway",
              url: "http://localhost:3000",
              transport: "STREAMABLEHTTP",
              enabled: true,
              visibility: "public",
              reachable: true,
              tool_count: 0,
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
            });
          }),
        );

        // Mock OAuth-related API calls to avoid unhandled MSW requests
        const triggerOAuthMock = vi
          .spyOn(serversApi, "triggerOAuthAuthorization")
          .mockResolvedValueOnce({
            type: "oauth_callback",
            status: "success",
            gatewayName: "Test OAuth Gateway",
          });
        vi.spyOn(serversApi, "toggleEnabled").mockResolvedValue({ status: "ok", message: "" });
        vi.spyOn(serversApi, "fetchToolsAfterOAuth").mockResolvedValue({
          success: true,
          message: "Done",
        });

        const { result } = renderHook(() => useMCPServerForm());
        const mockEvent = {
          preventDefault: vi.fn(),
        } as unknown as React.FormEvent<HTMLFormElement>;

        act(() => {
          result.current.setName("Test OAuth Gateway");
          result.current.setUrl("http://localhost:3000");
          result.current.setAuthType("oauth");
        });

        await act(async () => {
          await result.current.handleSubmit(mockEvent);
        });

        await waitFor(() => {
          expect(result.current.isSubmitting).toBe(false);
          expect(triggerOAuthMock).toHaveBeenCalledWith("new-gateway-123");
        });
      });

      it("should trigger OAuth authorization after successful gateway update with OAuth auth type", async () => {
        server.use(
          http.get("/gateways/existing-gateway", () => {
            return HttpResponse.json({
              id: "existing-gateway",
              name: "Existing Gateway",
              url: "http://localhost:3000",
              transport: "STREAMABLEHTTP",
              enabled: true,
              visibility: "public",
              reachable: true,
              tool_count: 0,
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
              authType: "oauth",
            });
          }),
          http.put("/gateways/existing-gateway", () => {
            return HttpResponse.json({
              id: "existing-gateway",
              name: "Updated OAuth Gateway",
              url: "http://localhost:3000",
              transport: "STREAMABLEHTTP",
              enabled: true,
              visibility: "public",
              reachable: true,
              tool_count: 0,
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
            });
          }),
        );

        // Mock OAuth-related API calls to avoid unhandled MSW requests
        const triggerOAuthMock = vi
          .spyOn(serversApi, "triggerOAuthAuthorization")
          .mockResolvedValueOnce({
            type: "oauth_callback",
            status: "success",
            gatewayName: "Updated OAuth Gateway",
          });
        vi.spyOn(serversApi, "toggleEnabled").mockResolvedValue({ status: "ok", message: "" });
        vi.spyOn(serversApi, "fetchToolsAfterOAuth").mockResolvedValue({
          success: true,
          message: "Done",
        });

        const { result } = renderHook(() => useMCPServerForm("existing-gateway"));
        const mockEvent = {
          preventDefault: vi.fn(),
        } as unknown as React.FormEvent<HTMLFormElement>;

        await waitFor(() => {
          expect(result.current.name).toBe("Existing Gateway");
        });

        act(() => {
          result.current.setName("Updated OAuth Gateway");
        });

        await act(async () => {
          await result.current.handleSubmit(mockEvent);
        });

        await waitFor(() => {
          expect(result.current.isSubmitting).toBe(false);
          expect(triggerOAuthMock).toHaveBeenCalledWith("existing-gateway");
        });
      });

      it("should not trigger OAuth authorization for non-OAuth auth types", async () => {
        server.use(
          http.post("/gateways", () => {
            return HttpResponse.json({
              id: "new-gateway-456",
              name: "Test Basic Auth Gateway",
              url: "http://localhost:3000",
              transport: "STREAMABLEHTTP",
              enabled: true,
              visibility: "public",
              reachable: true,
              tool_count: 0,
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
            });
          }),
        );

        const { result } = renderHook(() => useMCPServerForm());
        const mockEvent = {
          preventDefault: vi.fn(),
        } as unknown as React.FormEvent<HTMLFormElement>;

        act(() => {
          result.current.setName("Test Basic Auth Gateway");
          result.current.setUrl("http://localhost:3000");
          result.current.setAuthType("basic");
          result.current.setAuthUsername("user");
          result.current.setAuthPassword("pass");
        });

        await act(async () => {
          await result.current.handleSubmit(mockEvent);
        });

        await waitFor(() => {
          expect(result.current.isSubmitting).toBe(false);
        });
      });

      it("reuses the created gateway ID on OAuth retry to prevent duplicate gateway creation", async () => {
        let createCallCount = 0;
        server.use(
          http.post("/gateways", () => {
            createCallCount++;
            return HttpResponse.json({ id: "gateway-retry-test" });
          }),
        );

        const triggerOAuthMock = vi
          .spyOn(serversApi, "triggerOAuthAuthorization")
          .mockRejectedValueOnce(new Error("OAuth popup blocked"))
          .mockResolvedValueOnce({
            type: "oauth_callback",
            status: "success",
            gatewayName: "Test Gateway",
          });
        vi.spyOn(serversApi, "toggleEnabled").mockResolvedValue({ status: "ok", message: "" });
        vi.spyOn(serversApi, "fetchToolsAfterOAuth").mockResolvedValue({
          success: true,
          message: "Done",
        });

        const { result } = renderHook(() => useMCPServerForm());
        const mockEvent = {
          preventDefault: vi.fn(),
        } as unknown as React.FormEvent<HTMLFormElement>;

        act(() => {
          result.current.setName("Test Gateway");
          result.current.setUrl("http://localhost:3000");
          result.current.setAuthType("oauth");
        });

        // First submit: gateway is created, OAuth fails
        await act(async () => {
          await result.current.handleSubmit(mockEvent);
        });

        await waitFor(() => expect(result.current.oauthPending).toBe(false));
        expect(createCallCount).toBe(1);
        expect(result.current.oauthNotification?.type).toBe("error");

        // Second submit: gateway must NOT be created again — reuses stored ID
        await act(async () => {
          await result.current.handleSubmit(mockEvent);
        });

        await waitFor(() => expect(result.current.oauthPending).toBe(false));
        expect(createCallCount).toBe(1); // still 1 — no duplicate
        expect(triggerOAuthMock).toHaveBeenCalledTimes(2);
        expect(triggerOAuthMock).toHaveBeenCalledWith("gateway-retry-test");

        triggerOAuthMock.mockRestore();
      });

      it("delays onSuccess by 2 s after OAuth success so the notification is visible", async () => {
        vi.useFakeTimers();

        server.use(http.post("/gateways", () => HttpResponse.json({ id: "gateway-delay-test" })));

        const triggerOAuthMock = vi
          .spyOn(serversApi, "triggerOAuthAuthorization")
          .mockResolvedValueOnce({
            type: "oauth_callback",
            status: "success",
            gatewayName: "Delay Test",
          });
        vi.spyOn(serversApi, "toggleEnabled").mockResolvedValue({ status: "ok", message: "" });
        vi.spyOn(serversApi, "fetchToolsAfterOAuth").mockResolvedValue({
          success: true,
          message: "Done",
        });

        const { result } = renderHook(() => useMCPServerForm());
        const onSuccess = vi.fn();
        const mockEvent = {
          preventDefault: vi.fn(),
        } as unknown as React.FormEvent<HTMLFormElement>;

        act(() => {
          result.current.setName("Delay Test");
          result.current.setUrl("http://localhost:3000");
          result.current.setAuthType("oauth");
        });

        await act(async () => {
          await result.current.handleSubmit(mockEvent, onSuccess);
        });

        // Success notification must be set immediately
        expect(result.current.oauthNotification?.type).toBe("success");
        // But onSuccess must not have fired yet
        expect(onSuccess).not.toHaveBeenCalled();

        // After the 2-second delay onSuccess is called
        act(() => {
          vi.advanceTimersByTime(2000);
        });
        expect(onSuccess).toHaveBeenCalledTimes(1);

        vi.useRealTimers();
        triggerOAuthMock.mockRestore();
      });
    });
  });

  describe("fetchToolsNotification", () => {
    it("initializes fetchToolsNotification as null", () => {
      const { result } = renderHook(() => useMCPServerForm());
      expect(result.current.fetchToolsNotification).toBeNull();
    });

    it("exposes clearFetchToolsNotification as a function", () => {
      const { result } = renderHook(() => useMCPServerForm());
      expect(typeof result.current.clearFetchToolsNotification).toBe("function");
    });

    it("sets fetchToolsNotification to success after OAuth + successful tool fetch", async () => {
      server.use(http.post("/gateways", () => HttpResponse.json({ id: "gw-ft-success" })));

      vi.spyOn(serversApi, "triggerOAuthAuthorization").mockResolvedValueOnce({
        type: "oauth_callback",
        status: "success",
        gatewayName: "FT Success Gateway",
      });
      vi.spyOn(serversApi, "toggleEnabled").mockResolvedValueOnce({
        status: "ok",
        message: "activated",
      });
      vi.spyOn(serversApi, "fetchToolsAfterOAuth").mockResolvedValueOnce({
        success: true,
        message: "Successfully fetched and created 5 tools",
      });

      const { result } = renderHook(() => useMCPServerForm());
      const mockEvent = { preventDefault: vi.fn() } as unknown as React.FormEvent<HTMLFormElement>;

      act(() => {
        result.current.setName("FT Success Gateway");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("oauth");
      });

      await act(async () => {
        await result.current.handleSubmit(mockEvent);
      });

      await waitFor(() => {
        expect(result.current.fetchToolsNotification).toEqual({
          type: "success",
          message: "Successfully fetched and created 5 tools",
        });
      });
    });

    it("sets fetchToolsNotification to error with nested detail.message when fetch-tools fails", async () => {
      server.use(http.post("/gateways", () => HttpResponse.json({ id: "gw-ft-err" })));

      vi.spyOn(serversApi, "triggerOAuthAuthorization").mockResolvedValueOnce({
        type: "oauth_callback",
        status: "success",
        gatewayName: "FT Error Gateway",
      });
      vi.spyOn(serversApi, "toggleEnabled").mockResolvedValueOnce({
        status: "ok",
        message: "activated",
      });

      // Simulate the ApiError with nested detail.message structure
      const apiError = Object.assign(new Error("HTTP 400"), {
        name: "ApiError",
        status: 400,
        body: { detail: { message: "Failed to connect to MCP server", success: false } },
      });
      vi.spyOn(serversApi, "fetchToolsAfterOAuth").mockRejectedValueOnce(apiError);

      const { result } = renderHook(() => useMCPServerForm());
      const mockEvent = { preventDefault: vi.fn() } as unknown as React.FormEvent<HTMLFormElement>;

      act(() => {
        result.current.setName("FT Error Gateway");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("oauth");
      });

      await act(async () => {
        await result.current.handleSubmit(mockEvent);
      });

      await waitFor(() => {
        expect(result.current.fetchToolsNotification).toEqual({
          type: "error",
          message: "Failed to connect to MCP server",
        });
      });
    });

    it("sets fetchToolsNotification to error with plain detail string when fetch-tools fails", async () => {
      server.use(http.post("/gateways", () => HttpResponse.json({ id: "gw-ft-str-err" })));

      vi.spyOn(serversApi, "triggerOAuthAuthorization").mockResolvedValueOnce({
        type: "oauth_callback",
        status: "success",
        gatewayName: "FT String Error",
      });
      vi.spyOn(serversApi, "toggleEnabled").mockResolvedValueOnce({
        status: "ok",
        message: "activated",
      });

      const apiError = Object.assign(new Error("HTTP 404"), {
        name: "ApiError",
        status: 404,
        body: { detail: "Gateway not found" },
      });
      vi.spyOn(serversApi, "fetchToolsAfterOAuth").mockRejectedValueOnce(apiError);

      const { result } = renderHook(() => useMCPServerForm());
      const mockEvent = { preventDefault: vi.fn() } as unknown as React.FormEvent<HTMLFormElement>;

      act(() => {
        result.current.setName("FT String Error");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("oauth");
      });

      await act(async () => {
        await result.current.handleSubmit(mockEvent);
      });

      await waitFor(() => {
        expect(result.current.fetchToolsNotification).toEqual({
          type: "error",
          message: "Gateway not found",
        });
      });
    });

    it("clearFetchToolsNotification resets fetchToolsNotification to null", async () => {
      server.use(http.post("/gateways", () => HttpResponse.json({ id: "gw-clear-test" })));

      vi.spyOn(serversApi, "triggerOAuthAuthorization").mockResolvedValueOnce({
        type: "oauth_callback",
        status: "success",
      });
      vi.spyOn(serversApi, "toggleEnabled").mockResolvedValueOnce({ status: "ok", message: "" });
      vi.spyOn(serversApi, "fetchToolsAfterOAuth").mockResolvedValueOnce({
        success: true,
        message: "Done",
      });

      const { result } = renderHook(() => useMCPServerForm());
      const mockEvent = { preventDefault: vi.fn() } as unknown as React.FormEvent<HTMLFormElement>;

      act(() => {
        result.current.setName("Clear Test");
        result.current.setUrl("http://localhost:3000");
        result.current.setAuthType("oauth");
      });

      await act(async () => {
        await result.current.handleSubmit(mockEvent);
      });

      await waitFor(() => expect(result.current.fetchToolsNotification).not.toBeNull());

      act(() => result.current.clearFetchToolsNotification());

      expect(result.current.fetchToolsNotification).toBeNull();
    });
  });

  describe("handleSubmit error parsing", () => {
    it("extracts nested detail.message from API error on create failure", async () => {
      server.use(
        http.post("/gateways", () =>
          HttpResponse.json(
            { detail: { message: "A server with this name already exists", success: false } },
            { status: 400 },
          ),
        ),
      );

      const { result } = renderHook(() => useMCPServerForm());
      const mockEvent = { preventDefault: vi.fn() } as unknown as React.FormEvent<HTMLFormElement>;

      act(() => {
        result.current.setName("Duplicate Server");
        result.current.setUrl("http://localhost:3000");
      });

      await act(async () => {
        await result.current.handleSubmit(mockEvent);
      });

      await waitFor(() => {
        expect(result.current.errors.submit).toBe("A server with this name already exists");
      });
    });

    it("extracts plain detail string from API error on update failure", async () => {
      server.use(
        http.get("/gateways/edit-gw", () =>
          HttpResponse.json({ name: "My Server", url: "http://localhost:3000" }),
        ),
        http.put("/gateways/edit-gw", () =>
          HttpResponse.json({ detail: "Gateway not found" }, { status: 404 }),
        ),
      );

      const { result } = renderHook(() => useMCPServerForm("edit-gw"));
      const mockEvent = { preventDefault: vi.fn() } as unknown as React.FormEvent<HTMLFormElement>;

      await waitFor(() => expect(result.current.name).toBe("My Server"));

      await act(async () => {
        await result.current.handleSubmit(mockEvent);
      });

      await waitFor(() => {
        expect(result.current.errors.submit).toBe("Gateway not found");
      });
    });

    it("logs error and continues if activation fails during OAuth", async () => {
      server.use(http.post("/gateways", () => HttpResponse.json({ id: "gw-oauth-activate-fail" })));

      vi.spyOn(serversApi, "triggerOAuthAuthorization").mockResolvedValueOnce({
        type: "oauth_callback",
        status: "success",
      });
      const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
      vi.spyOn(serversApi, "toggleEnabled").mockRejectedValueOnce(new Error("Activation failed"));
      vi.spyOn(serversApi, "fetchToolsAfterOAuth").mockResolvedValueOnce({
        success: true,
        message: "ok",
      });

      const { result } = renderHook(() => useMCPServerForm());
      const mockEvent = { preventDefault: vi.fn() } as unknown as React.FormEvent<HTMLFormElement>;

      await act(async () => {
        result.current.setName("Test OAuth");
        result.current.setUrl("http://example.com");
        result.current.setAuthType("oauth");
      });

      await act(async () => {
        await result.current.handleSubmit(mockEvent);
      });

      expect(consoleErrorSpy).toHaveBeenCalledWith(
        "Failed to activate gateway after OAuth:",
        "An error occurred. Please try again.",
      );
    });
  });

  describe("validateField and isValid", () => {
    it("clears a field error when a value is valid (including advanced auth fields)", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.validateField("transport", "SSE");
        result.current.validateField("authUsername", "admin");
        result.current.validateField("authPassword", "s3cret-value");
        result.current.validateField("authToken", "token-123");
        result.current.validateField("caCertificate", "-----BEGIN CERTIFICATE-----");
        result.current.validateField("passthroughHeaders", "X-Trace, X-Env");
      });

      expect(result.current.errors.transport).toBeUndefined();
      expect(result.current.errors.authUsername).toBeUndefined();
    });

    it("sets a field error for an invalid transport value", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.validateField("transport", "NOT_A_TRANSPORT");
      });

      expect(result.current.errors.transport).toBeDefined();
    });

    it("is invalid for a non-http(s) URL", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("A server");
        result.current.setUrl("ftp://example.com/resource");
      });

      expect(result.current.isValid).toBe(false);
    });

    it("requires OAuth username and password for the password grant", () => {
      const { result } = renderHook(() => useMCPServerForm());

      act(() => {
        result.current.setName("A server");
        result.current.setUrl("https://example.com/mcp");
        result.current.setAuthType("oauth");
        result.current.setOAuthGrantType("password");
      });

      expect(result.current.isValid).toBe(false);
    });
  });
});

// Restore all spies after each test in this file
afterEach(() => {
  vi.restoreAllMocks();
});
