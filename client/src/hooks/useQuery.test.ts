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
    });
  });

  describe("validation and edge cases", () => {
    it("throws error for empty path string", () => {
      expect(() => renderHook(() => useQuery(""))).toThrow(
        "useQuery: path must be a non-empty string or null",
      );
    });

    it("throws error for non-string paths", () => {
      expect(() => renderHook(() => useQuery(123 as unknown as string))).toThrow(
        "useQuery: path must be a non-empty string or null",
      );
    });

    it("throws error for paths starting with double slash", () => {
      expect(() => renderHook(() => useQuery("//invalid"))).toThrow(
        "useQuery: path must be relative (no protocol)",
      );
    });

    it("rejects execute call when path is null", async () => {
      const { result } = renderHook(() => useQuery(null));
      await expect(result.current.execute()).rejects.toThrow(
        "useQuery: cannot execute a query without a path",
      );
    });
  });

  describe("PUT, PATCH, DELETE methods", () => {
    it("executes a PUT request", async () => {
      server.use(http.put("/test-put", () => HttpResponse.json({ updated: true })));

      const { result } = renderHook(() =>
        useQuery<{ updated: boolean }, { name: string }>("/test-put", {
          method: "PUT",
          enabled: false,
        }),
      );

      await act(async () => {
        const data = await result.current.execute({ name: "test" });
        expect(data).toEqual({ updated: true });
      });
    });

    it("executes a PATCH request", async () => {
      server.use(http.patch("/test-patch", () => HttpResponse.json({ patched: true })));

      const { result } = renderHook(() =>
        useQuery<{ patched: boolean }, { field: string }>("/test-patch", {
          method: "PATCH",
          enabled: false,
        }),
      );

      await act(async () => {
        const data = await result.current.execute({ field: "value" });
        expect(data).toEqual({ patched: true });
      });
    });

    it("executes a DELETE request", async () => {
      server.use(http.delete("/test-delete", () => HttpResponse.json({ deleted: true })));

      const { result } = renderHook(() =>
        useQuery<{ deleted: boolean }>("/test-delete", {
          method: "DELETE",
          enabled: false,
        }),
      );

      await act(async () => {
        const data = await result.current.execute();
        expect(data).toEqual({ deleted: true });
      });
    });
  });

  describe("initialData option", () => {
    it("starts with initialData and does not set isLoading", () => {
      const { result } = renderHook(() =>
        useQuery("/test-init", { initialData: { value: "preset" } }),
      );
      // With initialData provided, isLoading should be false immediately
      expect(result.current.data).toEqual({ value: "preset" });
      expect(result.current.isLoading).toBe(false);
    });
  });

  describe("headers option", () => {
    it("sends custom headers", async () => {
      server.use(http.get("/test-headers", () => HttpResponse.json({ ok: true })));

      const { result } = renderHook(() =>
        useQuery("/test-headers", {
          headers: { "X-Custom-Header": "value" },
        }),
      );

      await waitFor(() => expect(result.current.data).toBeDefined());
      expect(result.current.error).toBeNull();
    });
  });

  describe("execute error handling", () => {
    it("sets error state when execute fails", async () => {
      server.use(
        http.post("/test-exec-error", () =>
          HttpResponse.json({ detail: "Server error" }, { status: 500 }),
        ),
      );

      const { result } = renderHook(() =>
        useQuery("/test-exec-error", { method: "POST", enabled: false }),
      );

      await act(async () => {
        await expect(result.current.execute()).rejects.toBeTruthy();
      });

      expect(result.current.error).not.toBeNull();
    });
  });

  describe("immediate option", () => {
    it("does not auto-fetch when immediate is false and method is GET", () => {
      const { result } = renderHook(() => useQuery("/test-no-immediate", { immediate: false }));
      expect(result.current.isLoading).toBe(false);
      expect(result.current.data).toBeUndefined();
    });

    it("auto-fetches when immediate is true for non-GET method", async () => {
      server.use(http.post("/test-immediate-post", () => HttpResponse.json({ posted: true })));

      const { result } = renderHook(() =>
        useQuery("/test-immediate-post", { method: "POST", immediate: true }),
      );

      await waitFor(() => expect(result.current.data).toBeDefined());
      expect(result.current.data).toEqual({ posted: true });
    });
  });

  describe("refetch", () => {
    it("re-fetches data when refetch is called", async () => {
      let callCount = 0;
      server.use(
        http.get("/test-refetch", () => {
          callCount++;
          return HttpResponse.json({ count: callCount });
        }),
      );

      const { result } = renderHook(() => useQuery<{ count: number }>("/test-refetch"));

      await waitFor(() => expect(result.current.data).toBeDefined());
      expect(result.current.data?.count).toBe(1);

      await act(async () => {
        await result.current.refetch();
      });

      await waitFor(() => expect(result.current.data?.count).toBe(2));
    });
  });

  describe("execute with overrideBody", () => {
    it("sends overrideBody instead of default body", async () => {
      let receivedBody: unknown;
      server.use(
        http.post("/test-override-body", async ({ request }) => {
          receivedBody = await request.json();
          return HttpResponse.json({ ok: true });
        }),
      );

      const { result } = renderHook(() =>
        useQuery<{ ok: boolean }, { name: string }>("/test-override-body", {
          method: "POST",
          enabled: false,
          body: { name: "default" },
        }),
      );

      await act(async () => {
        await result.current.execute({ name: "override" });
      });

      expect(receivedBody).toEqual({ name: "override" });
    });
  });
});
