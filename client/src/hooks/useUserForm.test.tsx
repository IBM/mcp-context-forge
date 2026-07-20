import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { IntlProvider } from "react-intl";
import { useUserForm } from "./useUserForm";
import * as useQueryModule from "@/hooks/useQuery";
import type { ReactNode } from "react";
import type { User } from "@/types/user";

// Mock useQuery
vi.mock("@/hooks/useQuery", () => ({
  useQuery: vi.fn(),
}));

const messages = {
  "users.form.error.emailInvalid": "Invalid email address",
  "users.form.error.passwordMinLength": "Password must be at least 8 characters",
  "users.form.error.passwordsDoNotMatch": "Passwords do not match",
  "users.form.error.createFailed": "Failed to create user",
  "users.form.error.updateFailed": "Failed to update user",
};

const wrapper = ({ children }: { children: ReactNode }) => (
  <IntlProvider locale="en" messages={messages}>
    {children}
  </IntlProvider>
);

describe("useUserForm", () => {
  const mockExecute = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    vi.mocked(useQueryModule.useQuery).mockReturnValue({
      data: null,
      error: null,
      isLoading: false,
      execute: mockExecute,
      refetch: vi.fn(),
      setData: vi.fn(),
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe("initial state", () => {
    it("should initialize with default values", () => {
      const { result } = renderHook(() => useUserForm(), { wrapper });

      expect(result.current.email).toBe("");
      expect(result.current.password).toBe("");
      expect(result.current.confirmPassword).toBe("");
      expect(result.current.fullName).toBe("");
      expect(result.current.isAdmin).toBe(false);
      expect(result.current.isActive).toBe(true);
      expect(result.current.passwordChangeRequired).toBe(false);
      expect(result.current.errors).toEqual({});
      expect(result.current.isValid).toBe(false);
      expect(result.current.isSubmitting).toBe(false);
    });
  });

  describe("setters", () => {
    it("should update email", () => {
      const { result } = renderHook(() => useUserForm(), { wrapper });

      act(() => {
        result.current.setEmail("test@example.com");
      });

      expect(result.current.email).toBe("test@example.com");
    });

    it("should update password", () => {
      const { result } = renderHook(() => useUserForm(), { wrapper });

      act(() => {
        result.current.setPassword("SecurePass123!");
      });

      expect(result.current.password).toBe("SecurePass123!");
    });

    it("should update confirmPassword", () => {
      const { result } = renderHook(() => useUserForm(), { wrapper });

      act(() => {
        result.current.setConfirmPassword("SecurePass123!");
      });

      expect(result.current.confirmPassword).toBe("SecurePass123!");
    });

    it("should update fullName", () => {
      const { result } = renderHook(() => useUserForm(), { wrapper });

      act(() => {
        result.current.setFullName("John Doe");
      });

      expect(result.current.fullName).toBe("John Doe");
    });

    it("should update isAdmin", () => {
      const { result } = renderHook(() => useUserForm(), { wrapper });

      act(() => {
        result.current.setIsAdmin(true);
      });

      expect(result.current.isAdmin).toBe(true);
    });

    it("should update isActive", () => {
      const { result } = renderHook(() => useUserForm(), { wrapper });

      act(() => {
        result.current.setIsActive(false);
      });

      expect(result.current.isActive).toBe(false);
    });

    it("should update passwordChangeRequired", () => {
      const { result } = renderHook(() => useUserForm(), { wrapper });

      act(() => {
        result.current.setPasswordChangeRequired(true);
      });

      expect(result.current.passwordChangeRequired).toBe(true);
    });
  });

  describe("validateField", () => {
    it("should validate email field", () => {
      const { result } = renderHook(() => useUserForm(), { wrapper });

      act(() => {
        result.current.validateField("email", "invalid-email");
        vi.advanceTimersByTime(300);
      });

      expect(result.current.errors.email).toBe("Invalid email address");

      act(() => {
        result.current.validateField("email", "valid@example.com");
        vi.advanceTimersByTime(300);
      });

      expect(result.current.errors.email).toBeUndefined();
    });

    it("should validate password field", () => {
      const { result } = renderHook(() => useUserForm(), { wrapper });

      act(() => {
        result.current.validateField("password", "short");
        vi.advanceTimersByTime(300);
      });

      expect(result.current.errors.password).toBe("Password must be at least 8 characters");

      act(() => {
        result.current.validateField("password", "LongEnoughPassword123!");
        vi.advanceTimersByTime(300);
      });

      expect(result.current.errors.password).toBeUndefined();
    });

    it("should validate confirmPassword matches password", () => {
      const { result } = renderHook(() => useUserForm(), { wrapper });

      act(() => {
        result.current.setPassword("SecurePass123!");
        result.current.validateField("confirmPassword", "DifferentPass123!");
        vi.advanceTimersByTime(300);
      });

      expect(result.current.errors.confirmPassword).toBe("Passwords do not match");

      act(() => {
        result.current.validateField("confirmPassword", "SecurePass123!");
        vi.advanceTimersByTime(300);
      });

      expect(result.current.errors.confirmPassword).toBeUndefined();
    });
  });

  describe("validateForm", () => {
    it("should return false for empty form", () => {
      const { result } = renderHook(() => useUserForm(), { wrapper });

      let isValid: boolean = false;
      act(() => {
        isValid = result.current.validateForm();
      });

      expect(isValid).toBe(false);
      expect(Object.keys(result.current.errors).length).toBeGreaterThan(0);
    });

    it("should return false for invalid email", () => {
      const { result } = renderHook(() => useUserForm(), { wrapper });

      act(() => {
        result.current.setEmail("invalid-email");
        result.current.setPassword("SecurePass123!");
        result.current.setConfirmPassword("SecurePass123!");
      });

      let isValid: boolean = false;
      act(() => {
        isValid = result.current.validateForm();
      });

      expect(isValid).toBe(false);
      expect(result.current.errors.email).toBe("Invalid email address");
    });

    it("should return false for short password", () => {
      const { result } = renderHook(() => useUserForm(), { wrapper });

      act(() => {
        result.current.setEmail("test@example.com");
        result.current.setPassword("short");
        result.current.setConfirmPassword("short");
      });

      let isValid: boolean = false;
      act(() => {
        isValid = result.current.validateForm();
      });

      expect(isValid).toBe(false);
      expect(result.current.errors.password).toBe("Password must be at least 8 characters");
    });

    it("should return false for mismatched passwords", () => {
      const { result } = renderHook(() => useUserForm(), { wrapper });

      act(() => {
        result.current.setEmail("test@example.com");
        result.current.setPassword("SecurePass123!");
        result.current.setConfirmPassword("DifferentPass123!");
      });

      let isValid: boolean = false;
      act(() => {
        isValid = result.current.validateForm();
      });

      expect(isValid).toBe(false);
      expect(result.current.errors.confirmPassword).toBe("Passwords do not match");
    });

    it("should return true for valid form", () => {
      const { result } = renderHook(() => useUserForm(), { wrapper });

      act(() => {
        result.current.setEmail("test@example.com");
        result.current.setPassword("SecurePass123!");
        result.current.setConfirmPassword("SecurePass123!");
      });

      let isValid: boolean = false;
      act(() => {
        isValid = result.current.validateForm();
      });

      expect(isValid).toBe(true);
      expect(result.current.errors).toEqual({});
    });
  });

  describe("isValid computed property", () => {
    it("should be false for empty form", () => {
      const { result } = renderHook(() => useUserForm(), { wrapper });

      expect(result.current.isValid).toBe(false);
    });

    it("should be false for invalid email", () => {
      const { result } = renderHook(() => useUserForm(), { wrapper });

      act(() => {
        result.current.setEmail("invalid");
        result.current.setPassword("SecurePass123!");
        result.current.setConfirmPassword("SecurePass123!");
      });

      expect(result.current.isValid).toBe(false);
    });

    it("should be false for short password", () => {
      const { result } = renderHook(() => useUserForm(), { wrapper });

      act(() => {
        result.current.setEmail("test@example.com");
        result.current.setPassword("short");
        result.current.setConfirmPassword("short");
      });

      expect(result.current.isValid).toBe(false);
    });

    it("should be false for mismatched passwords", () => {
      const { result } = renderHook(() => useUserForm(), { wrapper });

      act(() => {
        result.current.setEmail("test@example.com");
        result.current.setPassword("SecurePass123!");
        result.current.setConfirmPassword("DifferentPass123!");
      });

      expect(result.current.isValid).toBe(false);
    });

    it("should be true for valid form", () => {
      const { result } = renderHook(() => useUserForm(), { wrapper });

      act(() => {
        result.current.setEmail("test@example.com");
        result.current.setPassword("SecurePass123!");
        result.current.setConfirmPassword("SecurePass123!");
      });

      expect(result.current.isValid).toBe(true);
    });
  });

  describe("resetForm", () => {
    it("should reset all fields to initial state", () => {
      const { result } = renderHook(() => useUserForm(), { wrapper });

      act(() => {
        result.current.setEmail("test@example.com");
        result.current.setPassword("SecurePass123!");
        result.current.setConfirmPassword("SecurePass123!");
        result.current.setFullName("John Doe");
        result.current.setIsAdmin(true);
        result.current.setIsActive(false);
        result.current.setPasswordChangeRequired(true);
      });

      act(() => {
        result.current.resetForm();
      });

      expect(result.current.email).toBe("");
      expect(result.current.password).toBe("");
      expect(result.current.confirmPassword).toBe("");
      expect(result.current.fullName).toBe("");
      expect(result.current.isAdmin).toBe(false);
      expect(result.current.isActive).toBe(true);
      expect(result.current.passwordChangeRequired).toBe(false);
      expect(result.current.errors).toEqual({});
    });
  });

  describe("getFormData", () => {
    it("should return form data in API format", () => {
      const { result } = renderHook(() => useUserForm(), { wrapper });

      act(() => {
        result.current.setEmail("test@example.com");
        result.current.setPassword("SecurePass123!");
        result.current.setFullName("John Doe");
        result.current.setIsAdmin(true);
        result.current.setIsActive(false);
        result.current.setPasswordChangeRequired(true);
      });

      const formData = result.current.getFormData();

      expect(formData).toEqual({
        email: "test@example.com",
        password: "SecurePass123!", // pragma: allowlist secret
        full_name: "John Doe",
        is_admin: true,
        is_active: false,
        password_change_required: true,
      });
    });

    it("should omit full_name if empty", () => {
      const { result } = renderHook(() => useUserForm(), { wrapper });

      act(() => {
        result.current.setEmail("test@example.com");
        result.current.setPassword("SecurePass123!");
      });

      const formData = result.current.getFormData();

      expect(formData.full_name).toBeUndefined();
    });
  });

  describe("handleSubmit", () => {
    it("should not submit invalid form", async () => {
      const { result } = renderHook(() => useUserForm(), { wrapper });
      const mockEvent = {
        preventDefault: vi.fn(),
      } as unknown as React.FormEvent<HTMLFormElement>;

      await act(async () => {
        await result.current.handleSubmit(mockEvent);
      });

      expect(mockEvent.preventDefault).toHaveBeenCalled();
      expect(mockExecute).not.toHaveBeenCalled();
    });

    it("should submit valid form", async () => {
      mockExecute.mockResolvedValue({ email: "test@example.com" });
      const { result } = renderHook(() => useUserForm(), { wrapper });

      act(() => {
        result.current.setEmail("test@example.com");
        result.current.setPassword("SecurePass123!");
        result.current.setConfirmPassword("SecurePass123!");
      });

      const mockEvent = {
        preventDefault: vi.fn(),
      } as unknown as React.FormEvent<HTMLFormElement>;

      await act(async () => {
        await result.current.handleSubmit(mockEvent);
      });

      expect(mockEvent.preventDefault).toHaveBeenCalled();
      expect(mockExecute).toHaveBeenCalledWith({
        email: "test@example.com",
        password: "SecurePass123!", // pragma: allowlist secret
        full_name: undefined,
        is_admin: false,
        is_active: true,
        password_change_required: false,
      });
    });

    it("should submit valid form in edit mode and handle success", async () => {
      mockExecute.mockResolvedValue({ email: "edit@example.com" });
      const initialUser = {
        email: "edit@example.com",
        is_admin: false,
        is_active: true,
        password_change_required: false,
      };
      const { result } = renderHook(
        () => useUserForm({ initialUser: initialUser as unknown as User }),
        {
          wrapper,
        },
      );
      const onSuccess = vi.fn();
      const onOptimisticUpdate = vi.fn();

      act(() => {
        result.current.setFullName("Updated Name");
      });

      const mockEvent = {
        preventDefault: vi.fn(),
      } as unknown as React.FormEvent<HTMLFormElement>;

      await act(async () => {
        await result.current.handleSubmit(
          mockEvent,
          onSuccess,
          undefined,
          undefined,
          onOptimisticUpdate,
        );
      });

      expect(mockEvent.preventDefault).toHaveBeenCalled();
      expect(onOptimisticUpdate).toHaveBeenCalledWith(
        "edit@example.com",
        expect.objectContaining({ full_name: "Updated Name" }),
      );
      expect(onSuccess).toHaveBeenCalledWith({ email: "edit@example.com" });
    });

    it("should handle error in edit mode", async () => {
      mockExecute.mockRejectedValue({
        body: {
          message: "Update failed",
        },
      });
      const initialUser = {
        email: "edit@example.com",
        is_admin: false,
        is_active: true,
        password_change_required: false,
      };
      const { result } = renderHook(
        () => useUserForm({ initialUser: initialUser as unknown as User }),
        {
          wrapper,
        },
      );
      const onError = vi.fn();

      act(() => {
        result.current.setFullName("Updated Name");
      });

      const mockEvent = {
        preventDefault: vi.fn(),
      } as unknown as React.FormEvent<HTMLFormElement>;

      await act(async () => {
        await result.current.handleSubmit(mockEvent, undefined, undefined, onError);
      });

      expect(mockEvent.preventDefault).toHaveBeenCalled();
      expect(onError).toHaveBeenCalled();
      expect(result.current.errors.submit).toBe("Update failed");
    });

    it("should clear timeouts on rapid validation", () => {
      const { result } = renderHook(() => useUserForm(), { wrapper });
      const clearTimeoutSpy = vi.spyOn(global, "clearTimeout");

      act(() => {
        result.current.validateField("email", "invalid1");
        result.current.validateField("email", "invalid2");
      });

      expect(clearTimeoutSpy).toHaveBeenCalled();
      clearTimeoutSpy.mockRestore();
    });

    it("should call onSuccess callback after successful submission", async () => {
      mockExecute.mockResolvedValue({ email: "test@example.com" });
      const { result } = renderHook(() => useUserForm(), { wrapper });
      const onSuccess = vi.fn();

      act(() => {
        result.current.setEmail("test@example.com");
        result.current.setPassword("SecurePass123!");
        result.current.setConfirmPassword("SecurePass123!");
      });

      const mockEvent = {
        preventDefault: vi.fn(),
      } as unknown as React.FormEvent<HTMLFormElement>;

      await act(async () => {
        await result.current.handleSubmit(mockEvent, onSuccess);
      });

      expect(onSuccess).toHaveBeenCalled();
    });

    it("should call onOptimisticCreate callback before API request", async () => {
      mockExecute.mockResolvedValue({ email: "test@example.com" });
      const { result } = renderHook(() => useUserForm(), { wrapper });
      const onOptimisticCreate = vi.fn();

      act(() => {
        result.current.setEmail("test@example.com");
        result.current.setPassword("SecurePass123!");
        result.current.setConfirmPassword("SecurePass123!");
      });

      const mockEvent = {
        preventDefault: vi.fn(),
      } as unknown as React.FormEvent<HTMLFormElement>;

      await act(async () => {
        await result.current.handleSubmit(mockEvent, undefined, onOptimisticCreate);
      });

      expect(onOptimisticCreate).toHaveBeenCalledWith(
        expect.objectContaining({
          email: "test@example.com",
          password: "SecurePass123!", // pragma: allowlist secret
        }),
      );
    });

    it("should reset form after successful submission", async () => {
      mockExecute.mockResolvedValue({ email: "test@example.com" });
      const { result } = renderHook(() => useUserForm(), { wrapper });

      act(() => {
        result.current.setEmail("test@example.com");
        result.current.setPassword("SecurePass123!");
        result.current.setConfirmPassword("SecurePass123!");
        result.current.setFullName("John Doe");
      });

      const mockEvent = {
        preventDefault: vi.fn(),
      } as unknown as React.FormEvent<HTMLFormElement>;

      await act(async () => {
        await result.current.handleSubmit(mockEvent);
      });

      expect(result.current.email).toBe("");
      expect(result.current.password).toBe("");
      expect(result.current.confirmPassword).toBe("");
      expect(result.current.fullName).toBe("");
    });

    it("should handle API error with message", async () => {
      mockExecute.mockRejectedValue({
        body: {
          message: "User already exists",
        },
      });
      const { result } = renderHook(() => useUserForm(), { wrapper });

      act(() => {
        result.current.setEmail("test@example.com");
        result.current.setPassword("SecurePass123!");
        result.current.setConfirmPassword("SecurePass123!");
      });

      const mockEvent = {
        preventDefault: vi.fn(),
      } as unknown as React.FormEvent<HTMLFormElement>;

      await act(async () => {
        await result.current.handleSubmit(mockEvent);
      });

      expect(result.current.errors.submit).toBe("User already exists");
    });

    it("should call onError callback with form data on API failure", async () => {
      mockExecute.mockRejectedValue({
        body: {
          message: "User already exists",
        },
      });
      const { result } = renderHook(() => useUserForm(), { wrapper });
      const onError = vi.fn();

      act(() => {
        result.current.setEmail("test@example.com");
        result.current.setPassword("SecurePass123!");
        result.current.setConfirmPassword("SecurePass123!");
        result.current.setFullName("John Doe");
      });

      const mockEvent = {
        preventDefault: vi.fn(),
      } as unknown as React.FormEvent<HTMLFormElement>;

      await act(async () => {
        await result.current.handleSubmit(mockEvent, undefined, undefined, onError);
      });

      expect(onError).toHaveBeenCalledWith({
        email: "test@example.com",
        password: "SecurePass123!", // pragma: allowlist secret
        full_name: "John Doe",
        is_admin: false,
        is_active: true,
        password_change_required: false,
      });
    });

    it("should handle API error with string detail", async () => {
      mockExecute.mockRejectedValue({
        body: {
          detail: "Invalid request",
        },
      });
      const { result } = renderHook(() => useUserForm(), { wrapper });

      act(() => {
        result.current.setEmail("test@example.com");
        result.current.setPassword("SecurePass123!");
        result.current.setConfirmPassword("SecurePass123!");
      });

      const mockEvent = {
        preventDefault: vi.fn(),
      } as unknown as React.FormEvent<HTMLFormElement>;

      await act(async () => {
        await result.current.handleSubmit(mockEvent);
      });

      expect(result.current.errors.submit).toBe("Invalid request");
    });

    it("should handle API error with validation errors", async () => {
      mockExecute.mockRejectedValue({
        body: {
          detail: [
            { loc: ["body", "email"], msg: "Invalid email format" },
            { loc: ["body", "password"], msg: "Password too weak" },
          ],
        },
      });
      const { result } = renderHook(() => useUserForm(), { wrapper });

      act(() => {
        result.current.setEmail("test@example.com");
        result.current.setPassword("SecurePass123!");
        result.current.setConfirmPassword("SecurePass123!");
      });

      const mockEvent = {
        preventDefault: vi.fn(),
      } as unknown as React.FormEvent<HTMLFormElement>;

      await act(async () => {
        await result.current.handleSubmit(mockEvent);
      });

      expect(result.current.errors.submit).toBe(
        "email: Invalid email format; password: Password too weak",
      );
    });

    it("should handle generic API error", async () => {
      mockExecute.mockRejectedValue(new Error("Network error"));
      const { result } = renderHook(() => useUserForm(), { wrapper });

      act(() => {
        result.current.setEmail("test@example.com");
        result.current.setPassword("SecurePass123!");
        result.current.setConfirmPassword("SecurePass123!");
      });

      const mockEvent = {
        preventDefault: vi.fn(),
      } as unknown as React.FormEvent<HTMLFormElement>;

      await act(async () => {
        await result.current.handleSubmit(mockEvent);
      });

      expect(result.current.errors.submit).toBe("Failed to create user");
    });
  });
});
