import { describe, it, expect, vi } from "vitest";
import { renderHook as rtlRenderHook, act, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { IntlProvider } from "react-intl";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import enMessages from "@/i18n/locales/en-US";
import { useGenerateSchemaFromOpenapi } from "./useGenerateSchemaFromOpenapi";

const ENDPOINT = "*/v1/tools/generate-schemas-from-openapi";

const wrapper = ({ children }: { children: ReactNode }) =>
  createElement(
    IntlProvider,
    { locale: "en", defaultLocale: "en", messages: enMessages },
    children,
  );

const renderHook = <Result, Props>(render: (initialProps: Props) => Result) =>
  rtlRenderHook(render, { wrapper });

function okResponse(overrides: Record<string, unknown> = {}) {
  return HttpResponse.json({
    success: true,
    input_schema: null,
    output_schema: null,
    spec_url: "https://api.example.com/openapi.json",
    message: "ok",
    ...overrides,
  });
}

describe("useGenerateSchemaFromOpenapi", () => {
  describe("URL guarding", () => {
    it.each(["javascript:alert(1)", "ftp://files.example.com/spec.json", "not-a-url", "   "])(
      "does not call the API for %s and does not report success",
      async (badUrl) => {
        const postSpy = vi.fn(() => okResponse());
        server.use(http.post(ENDPOINT, postSpy));
        const onSuccess = vi.fn();
        const onError = vi.fn();

        const { result } = renderHook(() => useGenerateSchemaFromOpenapi());

        await act(async () => {
          await result.current.generate({
            url: badUrl,
            requestType: "POST",
            onSuccess,
            onError,
          });
        });

        expect(postSpy).not.toHaveBeenCalled();
        expect(onSuccess).not.toHaveBeenCalled();
        expect(onError).not.toHaveBeenCalled();
        expect(result.current.isGenerating).toBe(false);
      },
    );
  });

  describe("request payload", () => {
    it("sends only url and request_type when no spec URL is set", async () => {
      let body: Record<string, unknown> | undefined;
      server.use(
        http.post(ENDPOINT, async ({ request }) => {
          body = (await request.json()) as Record<string, unknown>;
          return okResponse();
        }),
      );

      const { result } = renderHook(() => useGenerateSchemaFromOpenapi());

      await act(async () => {
        await result.current.generate({
          url: "https://api.example.com/endpoint",
          requestType: "PUT",
          onSuccess: vi.fn(),
        });
      });

      await waitFor(() => expect(body).toBeDefined());
      expect(body).toEqual({ url: "https://api.example.com/endpoint", request_type: "PUT" });
    });

    it("excludes a non-http spec URL from the request", async () => {
      let body: Record<string, unknown> | undefined;
      server.use(
        http.post(ENDPOINT, async ({ request }) => {
          body = (await request.json()) as Record<string, unknown>;
          return okResponse();
        }),
      );

      const { result } = renderHook(() => useGenerateSchemaFromOpenapi());

      act(() => result.current.setOpenApiSpecUrl("ftp://bad.example.com/spec.json"));
      await act(async () => {
        await result.current.generate({
          url: "https://api.example.com/endpoint",
          requestType: "GET",
          onSuccess: vi.fn(),
        });
      });

      await waitFor(() => expect(body).toBeDefined());
      expect(body?.openapi_url).toBeUndefined();
    });

    it("includes a valid https spec URL in the request", async () => {
      let body: Record<string, unknown> | undefined;
      server.use(
        http.post(ENDPOINT, async ({ request }) => {
          body = (await request.json()) as Record<string, unknown>;
          return okResponse();
        }),
      );

      const { result } = renderHook(() => useGenerateSchemaFromOpenapi());

      act(() => result.current.setOpenApiSpecUrl("https://api.example.com/openapi.json"));
      await act(async () => {
        await result.current.generate({
          url: "https://api.example.com/endpoint",
          requestType: "GET",
          onSuccess: vi.fn(),
        });
      });

      await waitFor(() => expect(body).toBeDefined());
      expect(body?.openapi_url).toBe("https://api.example.com/openapi.json");
    });
  });

  describe("success", () => {
    it("pretty-prints schemas, exposes the spec URL, and calls onSuccess", async () => {
      server.use(
        http.post(ENDPOINT, () =>
          okResponse({
            input_schema: { type: "object", properties: { a: { type: "string" } } },
            output_schema: { type: "object" },
          }),
        ),
      );
      const onSuccess = vi.fn();

      const { result } = renderHook(() => useGenerateSchemaFromOpenapi());

      await act(async () => {
        await result.current.generate({
          url: "https://api.example.com/endpoint",
          requestType: "POST",
          onSuccess,
        });
      });

      await waitFor(() => expect(onSuccess).toHaveBeenCalledOnce());
      expect(onSuccess).toHaveBeenCalledWith({
        inputSchema: JSON.stringify(
          { type: "object", properties: { a: { type: "string" } } },
          null,
          2,
        ),
        outputSchema: JSON.stringify({ type: "object" }, null, 2),
        specUrl: "https://api.example.com/openapi.json",
      });
      expect(result.current.generatedSpecUrl).toBe("https://api.example.com/openapi.json");
    });

    it("passes empty strings for null schemas", async () => {
      server.use(http.post(ENDPOINT, () => okResponse()));
      const onSuccess = vi.fn();

      const { result } = renderHook(() => useGenerateSchemaFromOpenapi());

      await act(async () => {
        await result.current.generate({
          url: "https://api.example.com/endpoint",
          requestType: "POST",
          onSuccess,
        });
      });

      await waitFor(() => expect(onSuccess).toHaveBeenCalledOnce());
      expect(onSuccess).toHaveBeenCalledWith(
        expect.objectContaining({ inputSchema: "", outputSchema: "" }),
      );
    });
  });

  describe("error status mapping", () => {
    const cases: Array<{ status: number; expected: string }> = [
      { status: 400, expected: "URL not reachable from the gateway (blocked by SSRF protection)" },
      {
        status: 502,
        expected: "Couldn't fetch the OpenAPI spec — check that the URL is correct and reachable",
      },
      {
        status: 500,
        expected: "Something went wrong while generating the schema. Please try again.",
      },
    ];

    it.each(cases)(
      "maps HTTP $status to a clear message and reveals the spec-URL fallback",
      async ({ status, expected }) => {
        server.use(
          http.post(ENDPOINT, () =>
            HttpResponse.json({ success: false, message: "backend detail" }, { status }),
          ),
        );
        const onError = vi.fn();
        const onSuccess = vi.fn();

        const { result } = renderHook(() => useGenerateSchemaFromOpenapi());

        await act(async () => {
          await result.current.generate({
            url: "https://api.example.com/endpoint",
            requestType: "POST",
            onSuccess,
            onError,
          });
        });

        await waitFor(() => expect(onError).toHaveBeenCalledWith(expected));
        expect(onSuccess).not.toHaveBeenCalled();
        expect(result.current.showSpecUrlInput).toBe(true);
        expect(result.current.generatedSpecUrl).toBe("");
      },
    );

    it("maps a 502 wrapping an upstream 401 to an auth-required message", async () => {
      server.use(
        http.post(ENDPOINT, () =>
          HttpResponse.json(
            { success: false, message: "OpenAPI spec server returned HTTP 401" },
            { status: 502 },
          ),
        ),
      );
      const onError = vi.fn();

      const { result } = renderHook(() => useGenerateSchemaFromOpenapi());

      await act(async () => {
        await result.current.generate({
          url: "https://api.example.com/endpoint",
          requestType: "POST",
          onSuccess: vi.fn(),
          onError,
        });
      });

      await waitFor(() =>
        expect(onError).toHaveBeenCalledWith(expect.stringContaining("requires authentication")),
      );
    });

    it("maps HTTP 404 to a message including the path and method", async () => {
      server.use(
        http.post(ENDPOINT, () =>
          HttpResponse.json({ success: false, message: "not found" }, { status: 404 }),
        ),
      );
      const onError = vi.fn();

      const { result } = renderHook(() => useGenerateSchemaFromOpenapi());

      await act(async () => {
        await result.current.generate({
          url: "https://api.example.com/v1/calculate",
          requestType: "POST",
          onSuccess: vi.fn(),
          onError,
        });
      });

      await waitFor(() =>
        expect(onError).toHaveBeenCalledWith(
          "The path /v1/calculate with method POST is not in the OpenAPI spec",
        ),
      );
    });

    it("calls onRequiresAuth when the backend reports requires_auth", async () => {
      server.use(
        http.post(ENDPOINT, () =>
          HttpResponse.json(
            { success: false, message: "auth", requires_auth: true },
            { status: 400 },
          ),
        ),
      );
      const onRequiresAuth = vi.fn();

      const { result } = renderHook(() => useGenerateSchemaFromOpenapi());

      await act(async () => {
        await result.current.generate({
          url: "https://api.example.com/endpoint",
          requestType: "POST",
          onSuccess: vi.fn(),
          onError: vi.fn(),
          onRequiresAuth,
        });
      });

      await waitFor(() => expect(onRequiresAuth).toHaveBeenCalledOnce());
    });

    it("reports a success:false body through onError and reveals the fallback", async () => {
      server.use(
        http.post(ENDPOINT, () =>
          HttpResponse.json({ success: false, message: "Custom backend message" }),
        ),
      );
      const onError = vi.fn();

      const { result } = renderHook(() => useGenerateSchemaFromOpenapi());

      await act(async () => {
        await result.current.generate({
          url: "https://api.example.com/endpoint",
          requestType: "POST",
          onSuccess: vi.fn(),
          onError,
        });
      });

      await waitFor(() => expect(onError).toHaveBeenCalledWith("Custom backend message"));
      expect(result.current.showSpecUrlInput).toBe(true);
    });
  });

  describe("reset", () => {
    it("clears generatedSpecUrl, spec URL input, and the fallback flag", async () => {
      server.use(
        http.post(ENDPOINT, () =>
          HttpResponse.json({ success: false, message: "boom" }, { status: 500 }),
        ),
      );

      const { result } = renderHook(() => useGenerateSchemaFromOpenapi());

      act(() => result.current.setOpenApiSpecUrl("https://api.example.com/openapi.json"));
      await act(async () => {
        await result.current.generate({
          url: "https://api.example.com/endpoint",
          requestType: "POST",
          onSuccess: vi.fn(),
          onError: vi.fn(),
        });
      });
      await waitFor(() => expect(result.current.showSpecUrlInput).toBe(true));

      act(() => result.current.reset());

      expect(result.current.showSpecUrlInput).toBe(false);
      expect(result.current.openApiSpecUrl).toBe("");
      expect(result.current.generatedSpecUrl).toBe("");
    });
  });
});
