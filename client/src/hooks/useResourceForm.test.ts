import { describe, it, expect, vi } from "vitest";
import { renderHook as rtlRenderHook, act, waitFor } from "@testing-library/react";
import { createElement, type FormEvent, type ReactNode } from "react";
import { IntlProvider } from "react-intl";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import enMessages from "@/i18n/locales/en-US";
import { useResourceForm } from "./useResourceForm";

const wrapper = ({ children }: { children: ReactNode }) =>
  createElement(
    IntlProvider,
    { locale: "en", defaultLocale: "en", messages: enMessages },
    children,
  );

const renderHook = <Result, Props>(render: (initialProps: Props) => Result) =>
  rtlRenderHook(render, { wrapper });

const fakeSubmit = (e?: Partial<FormEvent<HTMLFormElement>>) =>
  ({ preventDefault: vi.fn(), ...e }) as FormEvent<HTMLFormElement>;

describe("useResourceForm", () => {
  describe("Initial State", () => {
    it("initializes with empty fields and no errors", () => {
      const { result } = renderHook(() => useResourceForm());

      expect(result.current.uri).toBe("");
      expect(result.current.name).toBe("");
      expect(result.current.content).toBe("");
      expect(result.current.description).toBe("");
      expect(result.current.mimeType).toBe("");
      expect(result.current.tags).toBe("");
      expect(result.current.errors).toEqual({});
      expect(result.current.isSubmitting).toBe(false);
    });
  });

  describe("validateForm", () => {
    it("returns false and sets errors when required fields are empty", () => {
      const { result } = renderHook(() => useResourceForm());

      let valid: boolean;
      act(() => {
        valid = result.current.validateForm();
      });

      expect(valid!).toBe(false);
      expect(result.current.errors.uri).toBeTruthy();
      expect(result.current.errors.name).toBeTruthy();
      expect(result.current.errors.content).toBeTruthy();
    });

    it("returns true when required fields are filled", () => {
      const { result } = renderHook(() => useResourceForm());

      act(() => {
        result.current.setUri("resource://example/path");
        result.current.setName("My Resource");
        result.current.setContent("some content");
      });

      let valid: boolean;
      act(() => {
        valid = result.current.validateForm();
      });

      expect(valid!).toBe(true);
      expect(result.current.errors).toEqual({});
    });

    it("sets uri error when only uri is empty", () => {
      const { result } = renderHook(() => useResourceForm());

      act(() => {
        result.current.setName("My Resource");
        result.current.setContent("some content");
      });

      act(() => {
        result.current.validateForm();
      });

      expect(result.current.errors.uri).toBeTruthy();
      expect(result.current.errors.name).toBeUndefined();
      expect(result.current.errors.content).toBeUndefined();
    });
  });

  describe("getFormData", () => {
    it("splits tags string into array, trims whitespace", () => {
      const { result } = renderHook(() => useResourceForm());

      act(() => {
        result.current.setUri("resource://example/path");
        result.current.setName("My Resource");
        result.current.setContent("content");
        result.current.setTags("  tag1 , tag2,  tag3  ");
      });

      const data = result.current.getFormData();
      expect(data.resource.tags).toEqual(["tag1", "tag2", "tag3"]);
    });

    it("sets tags to undefined when empty", () => {
      const { result } = renderHook(() => useResourceForm());

      act(() => {
        result.current.setUri("resource://example/path");
        result.current.setName("My Resource");
        result.current.setContent("content");
      });

      const data = result.current.getFormData();
      expect(data.resource.tags).toBeUndefined();
    });

    it("filters empty tag entries after split", () => {
      const { result } = renderHook(() => useResourceForm());

      act(() => {
        result.current.setTags("tag1,,tag2");
      });

      const data = result.current.getFormData();
      expect(data.resource.tags).toEqual(["tag1", "tag2"]);
    });

    it("sanitizes control characters from string fields", () => {
      const { result } = renderHook(() => useResourceForm());

      act(() => {
        result.current.setUri("resource://ex\x00ample/path");
        result.current.setName("My\x0BResource");
        result.current.setContent("clean content");
        result.current.setDescription("desc\x1Fription");
      });

      const data = result.current.getFormData();
      expect(data.resource.uri).toBe("resource://example/path");
      expect(data.resource.name).toBe("MyResource");
      expect(data.resource.description).toBe("description");
    });

    it("omits optional fields when empty", () => {
      const { result } = renderHook(() => useResourceForm());

      act(() => {
        result.current.setUri("resource://example/path");
        result.current.setName("My Resource");
        result.current.setContent("content");
      });

      const data = result.current.getFormData();
      expect(data.resource.description).toBeUndefined();
      expect(data.resource.mimeType).toBeUndefined();
      expect(data.resource.tags).toBeUndefined();
    });
  });

  describe("visibility", () => {
    it("defaults to public", () => {
      const { result } = renderHook(() => useResourceForm());
      expect(result.current.visibility).toBe("public");
    });

    it("setVisibility updates the field", () => {
      const { result } = renderHook(() => useResourceForm());

      act(() => {
        result.current.setVisibility("private");
      });

      expect(result.current.visibility).toBe("private");
    });

    it("includes visibility in getFormData", () => {
      const { result } = renderHook(() => useResourceForm());

      act(() => {
        result.current.setUri("resource://example/path");
        result.current.setName("My Resource");
        result.current.setContent("content");
        result.current.setVisibility("team");
      });

      const data = result.current.getFormData();
      expect(data.resource.visibility).toBe("team");
    });
  });

  describe("handleSubmit", () => {
    it("calls execute with correct ResourceCreate payload", async () => {
      let capturedBody: unknown;
      server.use(
        http.post("*/resources", async ({ request }) => {
          capturedBody = await request.json();
          return HttpResponse.json({ id: "new-id" }, { status: 201 });
        }),
      );

      const { result } = renderHook(() => useResourceForm());

      act(() => {
        result.current.setUri("resource://example/path");
        result.current.setName("My Resource");
        result.current.setContent("some content");
        result.current.setMimeType("text/plain");
        result.current.setTags("a, b");
      });

      await act(async () => {
        await result.current.handleSubmit(fakeSubmit());
      });

      await waitFor(() => expect(capturedBody).toBeDefined());
      expect(capturedBody).toMatchObject({
        resource: {
          uri: "resource://example/path",
          name: "My Resource",
          content: "some content",
          mimeType: "text/plain",
          tags: ["a", "b"],
        },
      });
    });

    it("calls onSuccess callback on API success", async () => {
      server.use(
        http.post("*/resources", () => HttpResponse.json({ id: "new-id" }, { status: 201 })),
      );

      const onSuccess = vi.fn();
      const { result } = renderHook(() => useResourceForm());

      act(() => {
        result.current.setUri("resource://example/path");
        result.current.setName("My Resource");
        result.current.setContent("content");
      });

      await act(async () => {
        await result.current.handleSubmit(fakeSubmit(), onSuccess);
      });

      await waitFor(() => expect(onSuccess).toHaveBeenCalledOnce());
    });

    it("sets submitError on API failure", async () => {
      server.use(
        http.post("*/resources", () =>
          HttpResponse.json({ detail: "URI already exists" }, { status: 409 }),
        ),
      );

      const { result } = renderHook(() => useResourceForm());

      act(() => {
        result.current.setUri("resource://example/path");
        result.current.setName("My Resource");
        result.current.setContent("content");
      });

      await act(async () => {
        await result.current.handleSubmit(fakeSubmit());
      });

      await waitFor(() => expect(result.current.errors.submit).toBeTruthy());
    });

    it("does not call API when form is invalid", async () => {
      const postSpy = vi.fn(() => HttpResponse.json({}));
      server.use(http.post("*/resources", postSpy));

      const { result } = renderHook(() => useResourceForm());

      await act(async () => {
        await result.current.handleSubmit(fakeSubmit());
      });

      expect(postSpy).not.toHaveBeenCalled();
    });

    it("calls onBeforeSubmit with form data before API call", async () => {
      server.use(
        http.post("*/resources", () => HttpResponse.json({ id: "new-id" }, { status: 201 })),
      );

      const onBeforeSubmit = vi.fn();
      const { result } = renderHook(() => useResourceForm({ onBeforeSubmit }));

      act(() => {
        result.current.setUri("resource://example/path");
        result.current.setName("My Resource");
        result.current.setContent("content");
      });

      await act(async () => {
        await result.current.handleSubmit(fakeSubmit());
      });

      await waitFor(() => expect(onBeforeSubmit).toHaveBeenCalledOnce());
      expect(onBeforeSubmit).toHaveBeenCalledWith(
        expect.objectContaining({
          resource: expect.objectContaining({
            uri: "resource://example/path",
            name: "My Resource",
            content: "content",
          }),
        }),
      );
    });

    it("calls onError callback when API returns error", async () => {
      server.use(
        http.post("*/resources", () =>
          HttpResponse.json({ detail: "Internal error" }, { status: 500 }),
        ),
      );

      const onError = vi.fn();
      const { result } = renderHook(() => useResourceForm({ onError }));

      act(() => {
        result.current.setUri("resource://example/path");
        result.current.setName("My Resource");
        result.current.setContent("content");
      });

      await act(async () => {
        await result.current.handleSubmit(fakeSubmit());
      });

      await waitFor(() => expect(onError).toHaveBeenCalledOnce());
    });

    it("does not call onError on success", async () => {
      server.use(
        http.post("*/resources", () => HttpResponse.json({ id: "new-id" }, { status: 201 })),
      );

      const onError = vi.fn();
      const { result } = renderHook(() => useResourceForm({ onError }));

      act(() => {
        result.current.setUri("resource://example/path");
        result.current.setName("My Resource");
        result.current.setContent("content");
      });

      await act(async () => {
        await result.current.handleSubmit(fakeSubmit());
      });

      expect(onError).not.toHaveBeenCalled();
    });
  });

  describe("Edit mode (resourceId provided)", () => {
    it("initializes form state from initialValues", () => {
      const { result } = renderHook(() =>
        useResourceForm({
          resourceId: "resource-1",
          initialValues: {
            uri: "resource://example/path",
            name: "Existing Resource",
            content: "existing content",
            description: "existing description",
            mimeType: "text/plain",
            tags: "a, b",
            visibility: "private",
          },
        }),
      );

      expect(result.current.uri).toBe("resource://example/path");
      expect(result.current.name).toBe("Existing Resource");
      expect(result.current.content).toBe("existing content");
      expect(result.current.description).toBe("existing description");
      expect(result.current.mimeType).toBe("text/plain");
      expect(result.current.tags).toBe("a, b");
      expect(result.current.visibility).toBe("private");
    });

    it("sends a PUT request to resourcesApi.update when resourceId is provided", async () => {
      let capturedBody: unknown;
      let capturedMethod: string | undefined;
      server.use(
        http.put("*/resources/resource-1", async ({ request }) => {
          capturedMethod = request.method;
          capturedBody = await request.json();
          return HttpResponse.json({ id: "resource-1" }, { status: 200 });
        }),
      );

      const { result } = renderHook(() =>
        useResourceForm({
          resourceId: "resource-1",
          initialValues: {
            uri: "resource://example/path",
            name: "Existing Resource",
            content: "updated content",
          },
        }),
      );

      await act(async () => {
        await result.current.handleSubmit(fakeSubmit());
      });

      await waitFor(() => expect(capturedBody).toBeDefined());
      expect(capturedMethod).toBe("PUT");
      expect(capturedBody).toMatchObject({
        uri: "resource://example/path",
        name: "Existing Resource",
        content: "updated content",
      });
    });

    it("does not send a POST request to /resources when resourceId is provided", async () => {
      const postSpy = vi.fn(() => HttpResponse.json({ id: "new-id" }, { status: 201 }));
      server.use(
        http.post("*/resources", postSpy),
        http.put("*/resources/resource-1", () =>
          HttpResponse.json({ id: "resource-1" }, { status: 200 }),
        ),
      );

      const { result } = renderHook(() =>
        useResourceForm({
          resourceId: "resource-1",
          initialValues: { uri: "resource://example/path", name: "Existing", content: "c" },
        }),
      );

      await act(async () => {
        await result.current.handleSubmit(fakeSubmit());
      });

      expect(postSpy).not.toHaveBeenCalled();
    });

    it("calls onSuccess after a successful update", async () => {
      server.use(
        http.put("*/resources/resource-1", () =>
          HttpResponse.json({ id: "resource-1" }, { status: 200 }),
        ),
      );

      const onSuccess = vi.fn();
      const { result } = renderHook(() =>
        useResourceForm({
          resourceId: "resource-1",
          initialValues: { uri: "resource://example/path", name: "Existing", content: "c" },
        }),
      );

      await act(async () => {
        await result.current.handleSubmit(fakeSubmit(), onSuccess);
      });

      await waitFor(() => expect(onSuccess).toHaveBeenCalledOnce());
    });

    it("sets submitError with the update-failed message on API failure", async () => {
      server.use(
        http.put("*/resources/resource-1", () =>
          HttpResponse.json({ detail: "Update failed" }, { status: 500 }),
        ),
      );

      const { result } = renderHook(() =>
        useResourceForm({
          resourceId: "resource-1",
          initialValues: { uri: "resource://example/path", name: "Existing", content: "c" },
        }),
      );

      await act(async () => {
        await result.current.handleSubmit(fakeSubmit());
      });

      await waitFor(() => expect(result.current.errors.submit).toBeTruthy());
    });
  });

  describe("validateForm – name character restrictions", () => {
    // Mirrors backend SecurityValidator.validate_name (mcpgateway/common/validators.py),
    // which every resource name round-trips through on create and update.
    it.each(["valid_name", "valid-name-123", "valid.name", "Test Name", "Business Hours"])(
      "accepts name %s",
      (name) => {
        const { result } = renderHook(() => useResourceForm());

        act(() => {
          result.current.setUri("resource://example/path");
          result.current.setName(name);
          result.current.setContent("content");
        });

        let valid: boolean;
        act(() => {
          valid = result.current.validateForm();
        });

        expect(valid!).toBe(true);
        expect(result.current.errors.name).toBeUndefined();
      },
    );

    it.each([
      "Business Hours!",
      "name<script>",
      'name"test',
      "name'test",
      "name/test",
      "name,test",
      "name@test",
    ])("rejects name %s", (name) => {
      const { result } = renderHook(() => useResourceForm());

      act(() => {
        result.current.setUri("resource://example/path");
        result.current.setName(name);
        result.current.setContent("content");
      });

      let valid: boolean;
      act(() => {
        valid = result.current.validateForm();
      });

      expect(valid!).toBe(false);
      expect(result.current.errors.name).toBeTruthy();
    });

    it("rejects name longer than 255 characters", () => {
      const { result } = renderHook(() => useResourceForm());

      act(() => {
        result.current.setUri("resource://example/path");
        result.current.setName("a".repeat(256));
        result.current.setContent("content");
      });

      let valid: boolean;
      act(() => {
        valid = result.current.validateForm();
      });

      expect(valid!).toBe(false);
      expect(result.current.errors.name).toBeTruthy();
    });
  });

  describe("validateForm – description length", () => {
    it("returns false when description exceeds 500 chars", () => {
      const { result } = renderHook(() => useResourceForm());

      act(() => {
        result.current.setUri("resource://example/path");
        result.current.setName("My Resource");
        result.current.setContent("content");
        result.current.setDescription("a".repeat(501));
      });

      let valid: boolean;
      act(() => {
        valid = result.current.validateForm();
      });

      expect(valid!).toBe(false);
      expect(result.current.errors.description).toBeTruthy();
    });

    it("accepts description at exactly 500 chars", () => {
      const { result } = renderHook(() => useResourceForm());

      act(() => {
        result.current.setUri("resource://example/path");
        result.current.setName("My Resource");
        result.current.setContent("content");
        result.current.setDescription("a".repeat(500));
      });

      let valid: boolean;
      act(() => {
        valid = result.current.validateForm();
      });

      expect(valid!).toBe(true);
      expect(result.current.errors.description).toBeUndefined();
    });
  });
});
