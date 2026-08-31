import { describe, it, expect, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useCreateServerForm } from "./useCreateServerForm";
import React from "react";
import { I18nProvider } from "../i18n";

// ─────────────────────────────────────────────
// Wrapper with I18n (required for useIntl)
// ─────────────────────────────────────────────
function wrapper({ children }: { children: React.ReactNode }) {
  return <I18nProvider>{children}</I18nProvider>;
}

describe("useCreateServerForm", () => {
  it("initializes with default empty values", () => {
    const { result } = renderHook(() => useCreateServerForm(), { wrapper });
    expect(result.current.name).toBe("");
    expect(result.current.visibility).toBe("public");
    expect(result.current.oauthEnabled).toBe(false);
    expect(result.current.tags).toEqual([]);
    expect(result.current.description).toBe("");
    expect(result.current.errors).toEqual({});
  });

  it("accepts initialValues", () => {
    const { result } = renderHook(
      () =>
        useCreateServerForm({
          name: "My Server",
          visibility: "public",
          oauthEnabled: true,
          tags: ["api", "v2"],
          description: "A great server",
        }),
      { wrapper },
    );
    expect(result.current.name).toBe("My Server");
    expect(result.current.visibility).toBe("public");
    expect(result.current.oauthEnabled).toBe(true);
    expect(result.current.tags).toEqual(["api", "v2"]);
    expect(result.current.description).toBe("A great server");
  });

  it("setName updates name", () => {
    const { result } = renderHook(() => useCreateServerForm(), { wrapper });
    act(() => {
      result.current.setName("New Server");
    });
    expect(result.current.name).toBe("New Server");
  });

  it("setVisibility updates visibility", () => {
    const { result } = renderHook(() => useCreateServerForm(), { wrapper });
    act(() => {
      result.current.setVisibility("private");
    });
    expect(result.current.visibility).toBe("private");
  });

  it("setOAuthEnabled toggles oauth", () => {
    const { result } = renderHook(() => useCreateServerForm(), { wrapper });
    act(() => {
      result.current.setOAuthEnabled(true);
    });
    expect(result.current.oauthEnabled).toBe(true);
  });

  it("setTags updates tags array", () => {
    const { result } = renderHook(() => useCreateServerForm(), { wrapper });
    act(() => {
      result.current.setTags(["api", "rest"]);
    });
    expect(result.current.tags).toEqual(["api", "rest"]);
  });

  it("setDescription updates description", () => {
    const { result } = renderHook(() => useCreateServerForm(), { wrapper });
    act(() => {
      result.current.setDescription("New description");
    });
    expect(result.current.description).toBe("New description");
  });

  it("isValid is false for empty name", () => {
    const { result } = renderHook(() => useCreateServerForm(), { wrapper });
    expect(result.current.isValid).toBe(false);
  });

  it("isValid is true with valid name", () => {
    const { result } = renderHook(() => useCreateServerForm(), { wrapper });
    act(() => {
      result.current.setName("Valid Server");
    });
    expect(result.current.isValid).toBe(true);
  });

  it("validateForm returns false and sets errors for empty name", () => {
    const { result } = renderHook(() => useCreateServerForm(), { wrapper });
    let valid = false;
    act(() => {
      valid = result.current.validateForm();
    });
    expect(valid).toBe(false);
    expect(result.current.errors.name).toBeTruthy();
  });

  it("validateForm returns true for valid form", () => {
    const { result } = renderHook(() => useCreateServerForm(), { wrapper });
    act(() => {
      result.current.setName("My Server");
    });
    let valid = false;
    act(() => {
      valid = result.current.validateForm();
    });
    expect(valid).toBe(true);
    expect(result.current.errors).toEqual({});
  });

  it("validateField clears field error when field becomes valid", () => {
    const { result } = renderHook(() => useCreateServerForm(), { wrapper });
    // First validate to set errors
    act(() => {
      result.current.validateForm();
    });
    expect(result.current.errors.name).toBeTruthy();
    // Now validate the field with a valid value
    act(() => {
      result.current.validateField("name", "Good Name");
    });
    expect(result.current.errors.name).toBeUndefined();
  });

  it("validateField sets error for invalid field value", () => {
    const { result } = renderHook(() => useCreateServerForm(), { wrapper });
    act(() => {
      result.current.validateField("name", "");
    });
    expect(result.current.errors.name).toBeTruthy();
  });

  it("validateField ignores 'submit' field", () => {
    const { result } = renderHook(() => useCreateServerForm(), { wrapper });
    // Should not throw for 'submit' field
    act(() => {
      result.current.validateField("submit", "");
    });
    expect(result.current.errors.submit).toBeUndefined();
  });

  it("validateField ignores non-existent fields", () => {
    const { result } = renderHook(() => useCreateServerForm(), { wrapper });
    act(() => {
      // @ts-expect-error Testing invalid field
      result.current.validateField("nonexistent", "");
    });
    // Should not throw and should not add an error
    expect((result.current.errors as Record<string, unknown>).nonexistent).toBeUndefined();
  });

  it("resetForm clears values and errors", () => {
    const { result } = renderHook(() => useCreateServerForm(), { wrapper });
    act(() => {
      result.current.setName("Something");
      result.current.validateForm();
    });
    act(() => {
      result.current.resetForm();
    });
    expect(result.current.name).toBe("");
    expect(result.current.errors).toEqual({});
  });

  it("getFormData returns parsed data for valid form", () => {
    const { result } = renderHook(() => useCreateServerForm(), { wrapper });
    act(() => {
      result.current.setName("My Server");
      result.current.setDescription("Desc");
      result.current.setTags(["tag1", "tag2"]);
    });
    let data: ReturnType<typeof result.current.getFormData> | null = null;
    act(() => {
      data = result.current.getFormData();
    });
    expect(data!.name).toBe("My Server");
    expect(data!.description).toBe("Desc");
    expect(data!.tags).toEqual(["tag1", "tag2"]);
  });

  it("handleSubmit calls onSuccess with valid form data", () => {
    const { result } = renderHook(() => useCreateServerForm(), { wrapper });
    const onSuccess = vi.fn();
    act(() => {
      result.current.setName("My Server");
    });
    act(() => {
      const fakeEvent = { preventDefault: vi.fn() } as unknown as React.FormEvent<HTMLFormElement>;
      result.current.handleSubmit(fakeEvent, onSuccess);
    });
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(onSuccess.mock.calls[0][0].name).toBe("My Server");
  });

  it("handleSubmit does not call onSuccess when form is invalid", () => {
    const { result } = renderHook(() => useCreateServerForm(), { wrapper });
    const onSuccess = vi.fn();
    act(() => {
      const fakeEvent = { preventDefault: vi.fn() } as unknown as React.FormEvent<HTMLFormElement>;
      result.current.handleSubmit(fakeEvent, onSuccess);
    });
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("handleSubmit sets errors on invalid submission", () => {
    const { result } = renderHook(() => useCreateServerForm(), { wrapper });
    act(() => {
      const fakeEvent = { preventDefault: vi.fn() } as unknown as React.FormEvent<HTMLFormElement>;
      result.current.handleSubmit(fakeEvent);
    });
    expect(result.current.errors.name).toBeTruthy();
  });

  it("handleSubmit swallows non-ZodErrors thrown by onSuccess", () => {
    const { result } = renderHook(() => useCreateServerForm(), { wrapper });
    const onSuccess = vi.fn(() => {
      throw new Error("Normal error");
    });
    act(() => {
      result.current.setName("My Server");
    });
    act(() => {
      const fakeEvent = { preventDefault: vi.fn() } as unknown as React.FormEvent<HTMLFormElement>;
      result.current.handleSubmit(fakeEvent, onSuccess);
    });
    // Should not set any errors since it's not a ZodError
    expect(result.current.errors).toEqual({});
  });

  it("tags is undefined when no tags provided", () => {
    const { result } = renderHook(() => useCreateServerForm(), { wrapper });
    act(() => {
      result.current.setName("Server");
    });
    let data: ReturnType<typeof result.current.getFormData> | null = null;
    act(() => {
      data = result.current.getFormData();
    });
    expect(data!.tags).toBeUndefined();
  });

  it("sanitizes name by trimming whitespace", () => {
    const { result } = renderHook(() => useCreateServerForm(), { wrapper });
    act(() => {
      result.current.setName("  My Server  ");
    });
    let data: ReturnType<typeof result.current.getFormData> | null = null;
    act(() => {
      data = result.current.getFormData();
    });
    expect(data!.name).toBe("My Server");
  });
});
