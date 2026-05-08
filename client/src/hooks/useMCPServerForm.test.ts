import { describe, it, expect } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
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

      result.current.handleSubmit(mockEvent, () => {
        callbackCalled = true;
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

      result.current.handleSubmit(mockEvent);

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
  });
});

// Made with Bob
