import { describe, it, expect } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { useQuery } from "./useQuery";

describe("useQuery", () => {
  describe("refetch stability", () => {
    it("returns the same refetch reference across re-renders", async () => {
      server.use(http.get("/test-stable", () => HttpResponse.json({ value: 1 })));

      const { result, rerender } = renderHook(() => useQuery("/test-stable"));

      await waitFor(() => expect(result.current.data).toBeDefined());

      const refetchBefore = result.current.refetch;
      rerender();
      const refetchAfter = result.current.refetch;

      expect(refetchBefore).toBe(refetchAfter);
    });
  });

  describe("GET request", () => {
    it("fetches data and sets it on success", async () => {
      server.use(http.get("/test-get", () => HttpResponse.json({ hello: "world" })));

      const { result } = renderHook(() => useQuery<{ hello: string }>("/test-get"));

      await waitFor(() => expect(result.current.data).toEqual({ hello: "world" }));
      expect(result.current.error).toBeNull();
      expect(result.current.isLoading).toBe(false);
    });

    it("sets error state on non-2xx response", async () => {
      server.use(
        http.get("/test-error", () => HttpResponse.json({ detail: "Not found" }, { status: 404 })),
      );

      const { result } = renderHook(() => useQuery("/test-error"));

      await waitFor(() => expect(result.current.error).not.toBeNull());
      expect(result.current.error?.message).toBe("HTTP 404");
      expect(result.current.data).toBeUndefined();
    });

    it("does not fetch when enabled is false", () => {
      const { result } = renderHook(() => useQuery("/test-disabled", { enabled: false }));

      expect(result.current.isLoading).toBe(false);
      expect(result.current.data).toBeUndefined();
    });

    it("supports a null path for conditional queries", () => {
      const { result } = renderHook(() => useQuery(null));

      expect(result.current.isLoading).toBe(false);
      expect(result.current.data).toBeUndefined();
      expect(result.current.error).toBeNull();
    });
  });

  describe("manual execute (POST with enabled: false)", () => {
    it("does not run on mount and resolves when execute is called", async () => {
      server.use(http.post("/test-post", () => HttpResponse.json({ created: true })));

      const { result } = renderHook(() =>
        useQuery<{ created: boolean }, { name: string }>("/test-post", {
          method: "POST",
          enabled: false,
        }),
      );

      expect(result.current.isLoading).toBe(false);
      expect(result.current.data).toBeUndefined();

      let data: { created: boolean } | undefined;
      await act(async () => {
        data = await result.current.execute({ name: "test" });
      });

      expect(data).toEqual({ created: true });
      await waitFor(() => {
        expect(result.current.data).toEqual({ created: true });
      });
import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { useQuery } from "./useQuery";
import { api } from "@/api/client";

vi.mock("@/api/client", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

describe("useQuery", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("input validation", () => {
    it("throws when path is empty", () => {
      expect(() => {
        renderHook(() => useQuery(""));
      }).toThrow("useQuery: path must be a non-empty string");
    });

    it("throws when path starts with //", () => {
      expect(() => {
        renderHook(() => useQuery("//example.com/api"));
      }).toThrow("useQuery: path must be relative (no protocol)");
    });
  });

  describe("initial state", () => {
    it("starts loading for GET with no initialData", () => {
      vi.mocked(api.get).mockReturnValue(new Promise(() => {}));
      const { result } = renderHook(() => useQuery("/api/test"));

      expect(result.current.isLoading).toBe(true);
      expect(result.current.data).toBeUndefined();
      expect(result.current.error).toBeNull();
    });

    it("uses initialData when provided", () => {
      const { result } = renderHook(() =>
        useQuery("/api/test", { initialData: { name: "test" } }),
      );

      expect(result.current.data).toEqual({ name: "test" });
    });

    it("does not fetch when enabled is false", () => {
      const { result } = renderHook(() =>
        useQuery("/api/test", { enabled: false }),
      );

      expect(result.current.isLoading).toBe(false);
    });

    it("does not fetch immediately for POST by default", () => {
      const { result } = renderHook(() =>
        useQuery("/api/test", { method: "POST" }),
      );

      expect(result.current.isLoading).toBe(false);
    });

    it("fetches immediately for POST when immediate is true", () => {
      vi.mocked(api.post).mockReturnValue(new Promise(() => {}));
      const { result } = renderHook(() =>
        useQuery("/api/test", { method: "POST", immediate: true }),
      );

      expect(result.current.isLoading).toBe(true);
    });
  });

  describe("Cache Key and Request Options Serialization", () => {
    it("serializes custom headers inside cache key", async () => {
      vi.mocked(api.get).mockResolvedValue({ success: true });
      const { result } = renderHook(() =>
        useQuery("/api/test", { headers: { "X-Test": "123", "A-Header": "abc" } }),
      );
      await waitFor(() => expect(result.current.isLoading).toBe(false));
      expect(api.get).toHaveBeenCalledWith(
        "/api/test",
        { "X-Test": "123", "A-Header": "abc" },
        expect.any(AbortSignal),
      );
    });

    it("serializes body correctly, filtering proto/constructor properties", async () => {
      vi.mocked(api.post).mockResolvedValue({ success: true });
      const bodyWithSpecialKeys = {
        normalKey: "value",
        __proto__: { bad: "pollute" },
        constructor: "faker",
      };
      const { result } = renderHook(() =>
        useQuery("/api/test", { method: "POST", body: bodyWithSpecialKeys, immediate: true }),
      );
      await waitFor(() => expect(result.current.isLoading).toBe(false));
      expect(api.post).toHaveBeenCalledWith(
        "/api/test",
        bodyWithSpecialKeys,
        expect.objectContaining({ headers: undefined }),
      );
    });

    it("handles circular references in body gracefully during serialization", async () => {
      vi.mocked(api.post).mockResolvedValue({ success: true });
      const circular: any = { prop: "hello" };
      circular.self = circular;

      const consoleWarnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

      const { result } = renderHook(() =>
        useQuery("/api/test", { method: "POST", body: circular, immediate: true }),
      );

      await waitFor(() => expect(result.current.isLoading).toBe(false));
      expect(consoleWarnSpy).toHaveBeenCalled();
      consoleWarnSpy.mockRestore();
    });
  });

  describe("executeRequest methods (PATCH and DELETE)", () => {
    it("executes PATCH request correctly", async () => {
      vi.mocked(api.patch).mockResolvedValue({ patched: true });
      const { result } = renderHook(() =>
        useQuery("/api/test", { method: "PATCH", body: { foo: "bar" }, immediate: true }),
      );
      await waitFor(() => expect(result.current.isLoading).toBe(false));
      expect(api.patch).toHaveBeenCalledWith(
        "/api/test",
        { foo: "bar" },
        expect.objectContaining({ headers: undefined }),
      );
    });

    it("executes DELETE request correctly", async () => {
      vi.mocked(api.delete).mockResolvedValue({ deleted: true });
      const { result } = renderHook(() =>
        useQuery("/api/test", { method: "DELETE", immediate: true }),
      );
      await waitFor(() => expect(result.current.isLoading).toBe(false));
      expect(api.delete).toHaveBeenCalledWith(
        "/api/test",
        expect.objectContaining({ headers: undefined }),
      );
    });
  });

  describe("Error Sanitization", () => {
    it("sanitizes instances of Error with status, code, and body fields", async () => {
      const customError: any = new Error("Resource not found");
      customError.status = 404;
      customError.code = "NOT_FOUND";
      customError.body = { error: "details" };

      vi.mocked(api.get).mockRejectedValue(customError);

      const { result } = renderHook(() => useQuery("/api/test"));

      await waitFor(() => expect(result.current.isLoading).toBe(false));
      expect(result.current.error).toEqual({
        message: "Resource not found",
        status: 404,
        code: "NOT_FOUND",
        body: { error: "details" },
      });
    });

    it("sanitizes non-Error type exceptions gracefully", async () => {
      vi.mocked(api.get).mockRejectedValue("string error exception");

      const { result } = renderHook(() => useQuery("/api/test"));

      await waitFor(() => expect(result.current.isLoading).toBe(false));
      expect(result.current.error).toEqual({
        message: "An unexpected error occurred",
      });
    });
  });
});


