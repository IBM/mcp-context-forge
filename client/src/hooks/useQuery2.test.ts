import { describe, it, expect, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { useQuery } from "./useQuery";

describe("useQuery - additional coverage", () => {
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
