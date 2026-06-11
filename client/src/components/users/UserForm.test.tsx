import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { IntlProvider } from "react-intl";
import { UserForm } from "./UserForm";
import * as useUserFormModule from "@/hooks/useUserForm";

vi.mock("@/hooks/useUserForm");

const messages = {
  "users.form.title": "Create New User",
  "users.form.description": "Add a new user to the system",
  "users.form.email": "Email",
  "users.form.email.placeholder": "user@example.com",
  "users.form.password": "Password",
  "users.form.password.placeholder": "Enter password",
  "users.form.password.optional.placeholder": "Leave blank to keep current",
  "users.form.password.optional": "Leave blank to keep the current password",
  "users.form.password.show": "Show password",
  "users.form.password.hide": "Hide password",
  "users.form.confirmPassword": "Confirm Password", // pragma: allowlist secret
  "users.form.confirmPassword.placeholder": "Re-enter password",
  "users.form.fullName": "Full Name",
  "users.form.fullName.placeholder": "John Doe",
  "users.form.advancedSettings": "Advanced Settings",
  "users.form.isAdmin": "Administrator",
  "users.form.isActive": "Active",
  "users.form.passwordChangeRequired": "Require Password Change",
  "users.form.button.cancel": "Cancel",
  "users.form.button.create": "Create User",
  "users.form.button.creating": "Creating...",
  "users.form.button.save": "Save Changes",
  "users.form.button.saving": "Saving...",
  "users.edit.dialog.title": "Edit User",
  "users.edit.dialog.description": "Update account details for {email}",
};

const defaultFormState = {
  email: "",
  password: "", // pragma: allowlist secret
  confirmPassword: "", // pragma: allowlist secret
  fullName: "",
  isAdmin: false,
  isActive: true,
  passwordChangeRequired: false,
  errors: {},
  isValid: false,
  isSubmitting: false,
  isEditMode: false,
  setEmail: vi.fn(),
  setPassword: vi.fn(),
  setConfirmPassword: vi.fn(),
  setFullName: vi.fn(),
  setIsAdmin: vi.fn(),
  setIsActive: vi.fn(),
  setPasswordChangeRequired: vi.fn(),
  resetForm: vi.fn(),
  validateForm: vi.fn(),
  validateField: vi.fn(),
  handleSubmit: vi.fn(async () => {}),
  getFormData: vi.fn(),
};

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <IntlProvider locale="en" messages={messages}>
    {children}
  </IntlProvider>
);

describe("UserForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useUserFormModule.useUserForm).mockReturnValue(defaultFormState);
  });

  describe("visibility", () => {
    it("should not render when isOpen is false", () => {
      const { container } = render(<UserForm isOpen={false} onToggle={vi.fn()} />, { wrapper });

      expect(container.firstChild).toBeNull();
    });

    it("should render when isOpen is true", () => {
      render(<UserForm isOpen={true} onToggle={vi.fn()} />, { wrapper });

      expect(screen.getByText("Create New User")).toBeInTheDocument();
    });
  });

  describe("form fields", () => {
    it("should render all required fields", () => {
      render(<UserForm isOpen={true} onToggle={vi.fn()} />, { wrapper });

      expect(screen.getByLabelText(/Email/)).toBeInTheDocument();
      expect(screen.getByLabelText(/^Password/)).toBeInTheDocument();
      expect(screen.getByLabelText(/Confirm Password/)).toBeInTheDocument();
      expect(screen.getByLabelText(/Full Name/)).toBeInTheDocument();
    });

    it("should call setEmail when email input changes", () => {
      const setEmail = vi.fn();
      vi.mocked(useUserFormModule.useUserForm).mockReturnValue({
        ...defaultFormState,
        setEmail,
      });

      render(<UserForm isOpen={true} onToggle={vi.fn()} />, { wrapper });

      const emailInput = screen.getByLabelText(/Email/);
      fireEvent.change(emailInput, { target: { value: "test@example.com" } });

      expect(setEmail).toHaveBeenCalledWith("test@example.com");
    });

    it("should call setPassword when password input changes", () => {
      const setPassword = vi.fn();
      vi.mocked(useUserFormModule.useUserForm).mockReturnValue({
        ...defaultFormState,
        setPassword,
      });

      render(<UserForm isOpen={true} onToggle={vi.fn()} />, { wrapper });

      const passwordInput = screen.getByLabelText(/^Password/);
      fireEvent.change(passwordInput, { target: { value: "SecurePass123!" } });

      expect(setPassword).toHaveBeenCalledWith("SecurePass123!");
    });

    it("should call setConfirmPassword when confirm password input changes", () => {
      const setConfirmPassword = vi.fn();
      vi.mocked(useUserFormModule.useUserForm).mockReturnValue({
        ...defaultFormState,
        setConfirmPassword,
      });

      render(<UserForm isOpen={true} onToggle={vi.fn()} />, { wrapper });

      const confirmPasswordInput = screen.getByLabelText(/Confirm Password/);
      fireEvent.change(confirmPasswordInput, { target: { value: "SecurePass123!" } });

      expect(setConfirmPassword).toHaveBeenCalledWith("SecurePass123!");
    });

    it("should call setFullName when full name input changes", () => {
      const setFullName = vi.fn();
      vi.mocked(useUserFormModule.useUserForm).mockReturnValue({
        ...defaultFormState,
        setFullName,
      });

      render(<UserForm isOpen={true} onToggle={vi.fn()} />, { wrapper });

      const fullNameInput = screen.getByLabelText(/Full Name/);
      fireEvent.change(fullNameInput, { target: { value: "John Doe" } });

      expect(setFullName).toHaveBeenCalledWith("John Doe");
    });
  });

  describe("advanced settings", () => {
    it("should not show advanced settings by default", () => {
      render(<UserForm isOpen={true} onToggle={vi.fn()} />, { wrapper });

      expect(screen.queryByLabelText(/Administrator/)).not.toBeInTheDocument();
    });

    it("should toggle advanced settings when button is clicked", () => {
      render(<UserForm isOpen={true} onToggle={vi.fn()} />, { wrapper });

      const advancedButton = screen.getByText("Advanced Settings");
      fireEvent.click(advancedButton);

      expect(screen.getByLabelText(/Administrator/)).toBeInTheDocument();
      expect(screen.getByLabelText(/Active/)).toBeInTheDocument();
      expect(screen.getByLabelText(/Require Password Change/)).toBeInTheDocument();
    });

    it("should call setIsAdmin when admin checkbox is toggled", () => {
      const setIsAdmin = vi.fn();
      vi.mocked(useUserFormModule.useUserForm).mockReturnValue({
        ...defaultFormState,
        setIsAdmin,
      });

      render(<UserForm isOpen={true} onToggle={vi.fn()} />, { wrapper });

      const advancedButton = screen.getByText("Advanced Settings");
      fireEvent.click(advancedButton);

      const adminCheckbox = screen.getByLabelText(/Administrator/);
      fireEvent.click(adminCheckbox);

      expect(setIsAdmin).toHaveBeenCalledWith(true);
    });

    it("should call setIsActive when active checkbox is toggled", () => {
      const setIsActive = vi.fn();
      vi.mocked(useUserFormModule.useUserForm).mockReturnValue({
        ...defaultFormState,
        setIsActive,
      });

      render(<UserForm isOpen={true} onToggle={vi.fn()} />, { wrapper });

      const advancedButton = screen.getByText("Advanced Settings");
      fireEvent.click(advancedButton);

      const activeCheckbox = screen.getByLabelText(/Active/);
      fireEvent.click(activeCheckbox);

      expect(setIsActive).toHaveBeenCalledWith(false);
    });

    it("should call setPasswordChangeRequired when checkbox is toggled", () => {
      const setPasswordChangeRequired = vi.fn();
      vi.mocked(useUserFormModule.useUserForm).mockReturnValue({
        ...defaultFormState,
        setPasswordChangeRequired,
      });

      render(<UserForm isOpen={true} onToggle={vi.fn()} />, { wrapper });

      const advancedButton = screen.getByText("Advanced Settings");
      fireEvent.click(advancedButton);

      const passwordChangeCheckbox = screen.getByLabelText(/Require Password Change/);
      fireEvent.click(passwordChangeCheckbox);

      expect(setPasswordChangeRequired).toHaveBeenCalledWith(true);
    });
  });

  describe("error display", () => {
    it("should display email error with proper ARIA attributes", () => {
      vi.mocked(useUserFormModule.useUserForm).mockReturnValue({
        ...defaultFormState,
        errors: { email: "Invalid email address" },
      });

      render(<UserForm isOpen={true} onToggle={vi.fn()} />, { wrapper });

      const errorMessage = screen.getByText("Invalid email address");
      expect(errorMessage).toBeInTheDocument();
      expect(errorMessage).toHaveAttribute("role", "alert");
      expect(errorMessage).toHaveAttribute("aria-live", "polite");

      const emailInput = screen.getByLabelText(/Email/);
      expect(emailInput).toHaveAttribute("aria-invalid", "true");
      expect(emailInput).toHaveAttribute("aria-describedby", "user-email-error");
    });

    it("should display password error with proper ARIA attributes", () => {
      vi.mocked(useUserFormModule.useUserForm).mockReturnValue({
        ...defaultFormState,
        errors: { password: "Password too short" }, // pragma: allowlist secret
      });

      render(<UserForm isOpen={true} onToggle={vi.fn()} />, { wrapper });

      const errorMessage = screen.getByText("Password too short");
      expect(errorMessage).toBeInTheDocument();
      expect(errorMessage).toHaveAttribute("role", "alert");
      expect(errorMessage).toHaveAttribute("aria-live", "polite");
    });

    it("should display submit error with assertive aria-live", () => {
      vi.mocked(useUserFormModule.useUserForm).mockReturnValue({
        ...defaultFormState,
        errors: { submit: "Failed to create user" },
      });

      render(<UserForm isOpen={true} onToggle={vi.fn()} />, { wrapper });

      const errorContainer = screen.getByText("Failed to create user").parentElement;
      expect(errorContainer).toHaveAttribute("role", "alert");
      expect(errorContainer).toHaveAttribute("aria-live", "assertive");
    });
  });

  describe("form submission", () => {
    it("should call handleSubmit when form is submitted", async () => {
      const handleSubmit = vi.fn(async (event, callback) => {
        event.preventDefault();
        callback?.();
      });
      vi.mocked(useUserFormModule.useUserForm).mockReturnValue({
        ...defaultFormState,
        handleSubmit,
        isValid: true,
      });

      const onToggle = vi.fn();
      render(<UserForm isOpen={true} onToggle={onToggle} />, { wrapper });

      const submitButton = screen.getByText("Create User");
      fireEvent.click(submitButton);

      await waitFor(() => {
        expect(handleSubmit).toHaveBeenCalled();
      });
    });

    it("should call onSuccess callback when provided", async () => {
      const handleSubmit = vi.fn(async (event, callback) => {
        event.preventDefault();
        callback?.();
      });
      vi.mocked(useUserFormModule.useUserForm).mockReturnValue({
        ...defaultFormState,
        handleSubmit,
        isValid: true,
      });

      const onSuccess = vi.fn();
      render(<UserForm isOpen={true} onToggle={vi.fn()} onSuccess={onSuccess} />, { wrapper });

      const submitButton = screen.getByText("Create User");
      fireEvent.click(submitButton);

      await waitFor(() => {
        expect(onSuccess).toHaveBeenCalled();
      });
    });

    it("should call onToggle when no onSuccess callback provided", async () => {
      const handleSubmit = vi.fn(async (event, callback) => {
        event.preventDefault();
        callback?.();
      });
      vi.mocked(useUserFormModule.useUserForm).mockReturnValue({
        ...defaultFormState,
        handleSubmit,
        isValid: true,
      });

      const onToggle = vi.fn();
      render(<UserForm isOpen={true} onToggle={onToggle} />, { wrapper });

      const submitButton = screen.getByText("Create User");
      fireEvent.click(submitButton);

      await waitFor(() => {
        expect(onToggle).toHaveBeenCalled();
      });
    });

    it("should keep submit button enabled when form is invalid", () => {
      vi.mocked(useUserFormModule.useUserForm).mockReturnValue({
        ...defaultFormState,
        isValid: false,
      });

      render(<UserForm isOpen={true} onToggle={vi.fn()} />, { wrapper });

      const submitButton = screen.getByText("Create User");
      expect(submitButton).toBeEnabled();
    });

    it("should disable submit button when submitting", () => {
      vi.mocked(useUserFormModule.useUserForm).mockReturnValue({
        ...defaultFormState,
        isValid: true,
        isSubmitting: true,
      });

      render(<UserForm isOpen={true} onToggle={vi.fn()} />, { wrapper });

      const submitButton = screen.getByText("Creating...");
      expect(submitButton).toBeDisabled();
    });
  });

  describe("cancel button", () => {
    it("should call onToggle when cancel button is clicked", () => {
      const onToggle = vi.fn();
      render(<UserForm isOpen={true} onToggle={onToggle} />, { wrapper });

      const cancelButton = screen.getByText("Cancel");
      fireEvent.click(cancelButton);

      expect(onToggle).toHaveBeenCalled();
    });
  });

  describe("accessibility", () => {
    it("should have proper ARIA labels for required fields", () => {
      render(<UserForm isOpen={true} onToggle={vi.fn()} />, { wrapper });

      const emailLabel = screen.getByText(/Email/).closest("label");
      expect(emailLabel).toHaveTextContent("(required)");

      const passwordLabel = screen.getByText(/^Password/).closest("label");
      expect(passwordLabel).toHaveTextContent("(required)");

      const confirmPasswordLabel = screen.getByText(/Confirm Password/).closest("label");
      expect(confirmPasswordLabel).toHaveTextContent("(required)");
    });

    it("should have proper aria-expanded on advanced settings button", () => {
      render(<UserForm isOpen={true} onToggle={vi.fn()} />, { wrapper });

      const advancedButton = screen.getByText("Advanced Settings");
      expect(advancedButton).toHaveAttribute("aria-expanded", "false");

      fireEvent.click(advancedButton);
      expect(advancedButton).toHaveAttribute("aria-expanded", "true");
    });
  });
});
