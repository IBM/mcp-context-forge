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
      expect(() => renderHook(() => useQuery(""))).toThrow("useQuery: path must be a non-empty string or null");
    });

    it("throws error for non-string paths", () => {
      expect(() => renderHook(() => useQuery(123 as any))).toThrow("useQuery: path must be a non-empty string or null");
    });

    it("throws error for paths starting with double slash", () => {
      expect(() => renderHook(() => useQuery("//invalid"))).toThrow("useQuery: path must be relative (no protocol)");
    });

    it("rejects execute call when path is null", async () => {
      const { result } = renderHook(() => useQuery(null));
      await expect(result.current.execute()).rejects.toThrow("useQuery: cannot execute a query without a path");
    });
  });
});
