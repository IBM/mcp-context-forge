import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { api, ApiError, getToken, setToken, clearToken } from "./client";
import { server } from "@/test/mocks/server";

function clearCookie(name: string) {
  document.cookie = `${name}=; Max-Age=0; path=/`;
}

describe("api client", () => {
  afterEach(() => {
    clearCookie("mcpgateway_csrf_token");
    clearCookie("csrf_token");
    vi.clearAllMocks();
  });

  describe("CSRF Token Handling", () => {
    it("sends X-CSRF-Token from the configured mcpgateway CSRF cookie", async () => {
      document.cookie = "mcpgateway_csrf_token=new-token; path=/";

      let csrfHeader: string | null = null;
      server.use(
        http.post("*/csrf-check", ({ request }) => {
          csrfHeader = request.headers.get("X-CSRF-Token");
          return HttpResponse.json({ ok: true });
        }),
      );

      await api.post("/csrf-check", {});

      expect(csrfHeader).toBe("new-token");
    });

    it("does not use legacy csrf_token cookies", async () => {
      document.cookie = "csrf_token=legacy-token; path=/";

      let csrfHeader: string | null = null;
      server.use(
        http.post("*/csrf-check", ({ request }) => {
          csrfHeader = request.headers.get("X-CSRF-Token");
          return HttpResponse.json({ ok: true });
        }),
      );

      await api.post("/csrf-check", {});

      expect(csrfHeader).toBeNull();
    });

    it("does not send CSRF token for GET requests", async () => {
      document.cookie = "mcpgateway_csrf_token=token; path=/";

      let csrfHeader: string | null = null;
      server.use(
        http.get("*/api/test", ({ request }) => {
          csrfHeader = request.headers.get("X-CSRF-Token");
          return HttpResponse.json({ ok: true });
        }),
      );

      await api.get("/api/test");

      expect(csrfHeader).toBeNull();
    });

    it("sends CSRF token for PATCH requests", async () => {
      document.cookie = "mcpgateway_csrf_token=patch-token; path=/";

      let csrfHeader: string | null = null;
      server.use(
        http.patch("*/api/update", ({ request }) => {
          csrfHeader = request.headers.get("X-CSRF-Token");
          return HttpResponse.json({ ok: true });
        }),
      );

      await api.patch("/api/update", {});

      expect(csrfHeader).toBe("patch-token");
    });

    it("sends CSRF token for PUT requests", async () => {
      document.cookie = "mcpgateway_csrf_token=put-token; path=/";

      let csrfHeader: string | null = null;
      server.use(
        http.put("*/api/replace", ({ request }) => {
          csrfHeader = request.headers.get("X-CSRF-Token");
          return HttpResponse.json({ ok: true });
        }),
      );

      await api.put("/api/replace", {});

      expect(csrfHeader).toBe("put-token");
    });

    it("sends CSRF token for DELETE requests", async () => {
      document.cookie = "mcpgateway_csrf_token=delete-token; path=/";

      let csrfHeader: string | null = null;
      server.use(
        http.delete("*/api/item", ({ request }) => {
          csrfHeader = request.headers.get("X-CSRF-Token");
          return HttpResponse.json({ ok: true });
        }),
      );

      await api.delete("/api/item");

      expect(csrfHeader).toBe("delete-token");
    });
  });

  describe("HTTP Methods", () => {
    it("makes GET requests", async () => {
      let method: string | null = null;
      server.use(
        http.get("*/api/data", ({ request }) => {
          method = request.method;
          return HttpResponse.json({ result: "data" });
        }),
      );

      const result = await api.get("/api/data");

      expect(method).toBe("GET");
      expect(result).toEqual({ result: "data" });
    });

    it("makes POST requests with body", async () => {
      let receivedBody: unknown = null;
      server.use(
        http.post("*/api/create", async ({ request }) => {
          receivedBody = await request.json();
          return HttpResponse.json({ created: true });
        }),
      );

      const result = await api.post("/api/create", { name: "test" });

      expect(receivedBody).toEqual({ name: "test" });
      expect(result).toEqual({ created: true });
    });

    it("makes PUT requests with body", async () => {
      let receivedBody: unknown = null;
      server.use(
        http.put("*/api/update", async ({ request }) => {
          receivedBody = await request.json();
          return HttpResponse.json({ updated: true });
        }),
      );

      const result = await api.put("/api/update", { id: 1, name: "updated" });

      expect(receivedBody).toEqual({ id: 1, name: "updated" });
      expect(result).toEqual({ updated: true });
    });

    it("makes PATCH requests with body", async () => {
      let receivedBody: unknown = null;
      server.use(
        http.patch("*/api/partial", async ({ request }) => {
          receivedBody = await request.json();
          return HttpResponse.json({ patched: true });
        }),
      );

      const result = await api.patch("/api/partial", { status: "active" });

      expect(receivedBody).toEqual({ status: "active" });
      expect(result).toEqual({ patched: true });
    });

    it("makes DELETE requests", async () => {
      let method: string | null = null;
      server.use(
        http.delete("*/api/item/123", ({ request }) => {
          method = request.method;
          return HttpResponse.json({ deleted: true });
        }),
      );

      const result = await api.delete("/api/item/123");

      expect(method).toBe("DELETE");
      expect(result).toEqual({ deleted: true });
    });
  });

  describe("Headers", () => {
    it("sets Content-Type to application/json", async () => {
      let contentType: string | null = null;
      server.use(
        http.post("*/api/test", ({ request }) => {
          contentType = request.headers.get("Content-Type");
          return HttpResponse.json({ ok: true });
        }),
      );

      await api.post("/api/test", {});

      expect(contentType).toBe("application/json");
    });

    it("sets X-Requested-With header", async () => {
      let xRequestedWith: string | null = null;
      server.use(
        http.get("*/api/test", ({ request }) => {
          xRequestedWith = request.headers.get("X-Requested-With");
          return HttpResponse.json({ ok: true });
        }),
      );

      await api.get("/api/test");

      expect(xRequestedWith).toBe("XMLHttpRequest");
    });

    it("merges custom headers", async () => {
      let customHeader: string | null = null;
      server.use(
        http.get("*/api/test", ({ request }) => {
          customHeader = request.headers.get("X-Custom-Header");
          return HttpResponse.json({ ok: true });
        }),
      );

      await api.get("/api/test", { "X-Custom-Header": "custom-value" });

      expect(customHeader).toBe("custom-value");
    });
  });

  describe("Response Handling", () => {
    it("returns parsed JSON response", async () => {
      server.use(http.get("*/api/data", () => HttpResponse.json({ name: "test", value: 42 })));

      const result = await api.get("/api/data");

      expect(result).toEqual({ name: "test", value: 42 });
    });

    it("handles 204 No Content responses", async () => {
      server.use(http.delete("*/api/item", () => new HttpResponse(null, { status: 204 })));

      const result = await api.delete("/api/item");

      expect(result).toBeUndefined();
    });

    it("throws ApiError on non-2xx responses", async () => {
      server.use(
        http.get("*/api/error", () => HttpResponse.json({ error: "Not found" }, { status: 404 })),
      );

      await expect(api.get("/api/error")).rejects.toThrow(ApiError);
    });

    it("includes status and body in ApiError", async () => {
      const errorBody = { error: "validation failed" };
      server.use(http.post("*/api/validate", () => HttpResponse.json(errorBody, { status: 400 })));

      try {
        await api.post("/api/validate", {});
      } catch (e) {
        expect(e).toBeInstanceOf(ApiError);
        expect((e as ApiError).status).toBe(400);
        expect((e as ApiError).body).toEqual(errorBody);
      }
    });

    it("handles invalid JSON in error response", async () => {
      server.use(http.get("*/api/error", () => new HttpResponse("Invalid JSON", { status: 500 })));

      try {
        await api.get("/api/error");
      } catch (e) {
        expect(e).toBeInstanceOf(ApiError);
        expect((e as ApiError).status).toBe(500);
        expect((e as ApiError).body).toBeNull();
      }
    });
  });

  describe("Authentication", () => {
    it("redirects to login on 401 response", async () => {
      const originalLocation = window.location;
      const mockReplace = vi.fn();
      delete (window as unknown as { location?: unknown }).location;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      window.location = { ...originalLocation, replace: mockReplace } as any;

      server.use(http.get("*/api/protected", () => new HttpResponse(null, { status: 401 })));

      try {
        await api.get("/api/protected");
      } catch {
        // expected
      }

      expect(mockReplace).toHaveBeenCalledWith("/app/login");

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      window.location = originalLocation as any;
    });

    it("preserves the current app page as a next param on 401", async () => {
      const originalLocation = window.location;
      const mockReplace = vi.fn();
      const fakeLocation: Location = {
        ...originalLocation,
        pathname: "/app/tools",
        search: "",
        replace: mockReplace,
      };
      Object.defineProperty(window, "location", { value: fakeLocation, configurable: true });

      server.use(http.get("*/api/protected", () => new HttpResponse(null, { status: 401 })));

      try {
        await api.get("/api/protected");
      } catch {
        // expected
      }

      expect(mockReplace).toHaveBeenCalledWith("/app/login?next=%2Fapp%2Ftools");

      Object.defineProperty(window, "location", { value: originalLocation, configurable: true });
    });

    it("does not redirect to login on 401 for /app/auth/me", async () => {
      const originalLocation = window.location;
      const mockReplace = vi.fn();
      delete (window as unknown as { location?: unknown }).location;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      window.location = { ...originalLocation, replace: mockReplace } as any;

      server.use(http.get("*/app/auth/me", () => new HttpResponse(null, { status: 401 })));

      try {
        await api.get("/app/auth/me");
      } catch {
        // expected
      }

      expect(mockReplace).not.toHaveBeenCalled();

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      window.location = originalLocation as any;
    });

    it("sends credentials same-origin for authenticated requests", async () => {
      let credentialsMode: RequestCredentials | undefined;
      const originalFetch = global.fetch;
      global.fetch = vi.fn(async (_url, options) => {
        credentialsMode = options?.credentials;
        return new Response(JSON.stringify({ ok: true }));
      });

      await api.get("/api/test");

      expect(credentialsMode).toBe("same-origin");

      global.fetch = originalFetch;
    });
  });

  describe("URL Handling", () => {
    it("accepts absolute URLs", async () => {
      let requestUrl: string | null = null;
      server.use(
        http.get("https://example.com/api/data", ({ request }) => {
          requestUrl = request.url;
          return HttpResponse.json({ ok: true });
        }),
      );

      await api.get("https://example.com/api/data");

      expect(requestUrl).toContain("example.com/api/data");
    });

    it("converts relative URLs to absolute", async () => {
      let requestUrl: string | null = null;
      server.use(
        http.get("*/api/data", ({ request }) => {
          requestUrl = request.url;
          return HttpResponse.json({ ok: true });
        }),
      );

      await api.get("/api/data");

      expect(requestUrl).toContain("/api/data");
    });
  });

  describe("Token Functions (backward compatibility)", () => {
    it("getToken returns null", () => {
      const token = getToken();
      expect(token).toBeNull();
    });

    it("setToken is a no-op", () => {
      expect(() => setToken()).not.toThrow();
    });

    it("clearToken is a no-op", () => {
      expect(() => clearToken()).not.toThrow();
    });
  });

  describe("ApiError Class", () => {
    it("has correct error name", () => {
      const error = new ApiError(404, { message: "not found" }, "Not Found");
      expect(error.name).toBe("ApiError");
    });

    it("includes status in error properties", () => {
      const error = new ApiError(500, null, "Server Error");
      expect(error.status).toBe(500);
    });

    it("includes body in error properties", () => {
      const body = { error: "validation failed" };
      const error = new ApiError(400, body, "Bad Request");
      expect(error.body).toEqual(body);
    });

    it("extends Error class", () => {
      const error = new ApiError(404, null, "Not Found");
      expect(error).toBeInstanceOf(Error);
      expect(error.message).toBe("Not Found");
    });
  });

  describe("Options Handling", () => {
    it("accepts custom headers in api.get", async () => {
      let authHeader: string | null = null;
      server.use(
        http.get("*/api/test", ({ request }) => {
          authHeader = request.headers.get("Authorization");
          return HttpResponse.json({ ok: true });
        }),
      );

      await api.get("/api/test", { Authorization: "Bearer token123" });

      expect(authHeader).toBe("Bearer token123");
    });

    it("accepts authenticated option in api.post", async () => {
      document.cookie = "mcpgateway_csrf_token=csrf; path=/";

      let csrfHeader: string | null = null;
      server.use(
        http.post("*/api/public", ({ request }) => {
          csrfHeader = request.headers.get("X-CSRF-Token");
          return HttpResponse.json({ ok: true });
        }),
      );

      await api.post("/api/public", {}, { authenticated: false });

      expect(csrfHeader).toBeNull();
    });

    it("passes through options to request function", async () => {
      server.use(http.delete("*/api/item", () => HttpResponse.json({ deleted: true })));

      const result = await api.delete("/api/item", { authenticated: true });

      expect(result).toEqual({ deleted: true });
    });
  });
});
