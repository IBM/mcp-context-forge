import { useState, useCallback, useMemo, type FormEvent } from "react";
import { z } from "zod";
import { useIntl } from "react-intl";
import { useQuery } from "@/hooks/useQuery";
import { sanitizeString, sanitizePassword } from "@/lib/sanitize";
import { VALIDATION } from "@/lib/constants";
import { parseApiError } from "@/lib/errorUtils";
import type { User, CreateUserRequest } from "@/types/user";

// Zod schema factory that accepts intl for localized messages
const createUserFormObjectSchema = (intl: ReturnType<typeof useIntl>) =>
  z.object({
    email: z
      .string()
      .transform((val) => sanitizeString(val, VALIDATION.MAX_EMAIL_LENGTH))
      .pipe(
        z
          .string()
          .email(intl.formatMessage({ id: "users.form.error.emailInvalid" })),
      ),
    password: z
      .string()
      .transform((val) => sanitizePassword(val, VALIDATION.MAX_PASSWORD_LENGTH))
      .pipe(
        z
          .string()
          .min(VALIDATION.MIN_PASSWORD_LENGTH, intl.formatMessage({ id: "users.form.error.passwordMinLength" })),
      ),
    confirmPassword: z.string(),
    fullName: z
      .string()
      .transform((val) => sanitizeString(val, VALIDATION.MAX_NAME_LENGTH))
      .optional(),
    isAdmin: z.boolean().default(false),
    isActive: z.boolean().default(true),
    passwordChangeRequired: z.boolean().default(false),
  });

const createUserFormSchema = (intl: ReturnType<typeof useIntl>) =>
  createUserFormObjectSchema(intl).refine(
    (data) => data.password === data.confirmPassword, // pragma: allowlist secret
    {
      message: intl.formatMessage({ id: "users.form.error.passwordsDoNotMatch" }),
      path: ["confirmPassword"],
    },
  );

export type UserFormData = z.infer<ReturnType<typeof createUserFormSchema>>;

export interface FormErrors {
  email?: string;
  password?: string;
  confirmPassword?: string;
  fullName?: string;
  isAdmin?: string;
  isActive?: string;
  passwordChangeRequired?: string;
  submit?: string;
}

export interface UseUserFormReturn {
  // Form state
  email: string;
  password: string; // pragma: allowlist secret
  confirmPassword: string; // pragma: allowlist secret
  fullName: string;
  isAdmin: boolean;
  isActive: boolean;
  passwordChangeRequired: boolean;
  errors: FormErrors;
  isValid: boolean;
  isSubmitting: boolean;

  // Setters
  setEmail: (value: string) => void;
  setPassword: (value: string) => void; // pragma: allowlist secret
  setConfirmPassword: (value: string) => void; // pragma: allowlist secret
  setFullName: (value: string) => void;
  setIsAdmin: (value: boolean) => void;
  setIsActive: (value: boolean) => void;
  setPasswordChangeRequired: (value: boolean) => void;

  // Field-level validation
  validateField: (field: keyof FormErrors, value: string | boolean) => void;

  // Actions
  resetForm: () => void;
  validateForm: () => boolean;
  handleSubmit: (event: FormEvent<HTMLFormElement>, onSuccess?: () => void) => Promise<void>;
  getFormData: () => CreateUserRequest;
}

const initialState = {
  email: "",
  password: "", // pragma: allowlist secret
  confirmPassword: "", // pragma: allowlist secret
  fullName: "",
  isAdmin: false,
  isActive: true,
  passwordChangeRequired: false,
};

export function useUserForm(): UseUserFormReturn {
  const intl = useIntl();
  const [email, setEmail] = useState(initialState.email);
  const [password, setPassword] = useState(initialState.password);
  const [confirmPassword, setConfirmPassword] = useState(initialState.confirmPassword);
  const [fullName, setFullName] = useState(initialState.fullName);
  const [isAdmin, setIsAdmin] = useState(initialState.isAdmin);
  const [isActive, setIsActive] = useState(initialState.isActive);
  const [passwordChangeRequired, setPasswordChangeRequired] = useState(
    initialState.passwordChangeRequired,
  );
  const [errors, setErrors] = useState<FormErrors>({});

  // Create localized schemas
  const userFormObjectSchema = useMemo(() => createUserFormObjectSchema(intl), [intl]);
  const userFormSchema = useMemo(() => createUserFormSchema(intl), [intl]);

  // Use useQuery for POST request to create user
  const { execute: createUser, isLoading: isSubmitting } = useQuery<User, CreateUserRequest>(
    "/auth/email/admin/users",
    {
      method: "POST",
      enabled: false, // Don't execute immediately
    },
  );

  const getFormData = useCallback((): CreateUserRequest => {
    return {
      email,
      password,
      full_name: fullName || undefined,
      is_admin: isAdmin,
      is_active: isActive,
      password_change_required: passwordChangeRequired,
    };
  }, [email, password, fullName, isAdmin, isActive, passwordChangeRequired]);

  const validateField = useCallback(
    (field: keyof FormErrors, value: string | boolean) => {
      try {
        const fieldSchema =
          userFormObjectSchema.shape[field as keyof typeof userFormObjectSchema.shape];
        if (fieldSchema) {
          fieldSchema.parse(value);
          setErrors((prev) => {
            const newErrors = { ...prev };
            delete newErrors[field];
            return newErrors;
          });
        }

        // Special handling for confirmPassword
        if (field === "confirmPassword" && typeof value === "string") {
          if (value !== password) {
            setErrors((prev) => ({
              ...prev,
              confirmPassword: intl.formatMessage({ id: "users.form.error.passwordsDoNotMatch" }), // pragma: allowlist secret
            }));
          } else {
            setErrors((prev) => {
              const newErrors = { ...prev };
              delete newErrors.confirmPassword;
              return newErrors;
            });
          }
        }
      } catch (error) {
        if (error instanceof z.ZodError) {
          setErrors((prev) => ({
            ...prev,
            [field]: error.issues[0]?.message || "Invalid value",
          }));
        }
      }
    },
    [password, userFormObjectSchema, intl],
  );

  const validateForm = useCallback((): boolean => {
    try {
      const formData = {
        email,
        password,
        confirmPassword,
        fullName,
        isAdmin,
        isActive,
        passwordChangeRequired,
      };
      userFormSchema.parse(formData);
      setErrors({});
      return true;
    } catch (error) {
      if (error instanceof z.ZodError) {
        const newErrors: FormErrors = {};
        error.issues.forEach((issue) => {
          const path = issue.path[0] as keyof FormErrors;
          newErrors[path] = issue.message;
        });
        setErrors(newErrors);
      }
      return false;
    }
  }, [email, password, confirmPassword, fullName, isAdmin, isActive, passwordChangeRequired, userFormSchema]);

  const resetForm = useCallback(() => {
    setEmail(initialState.email);
    setPassword(initialState.password);
    setConfirmPassword(initialState.confirmPassword);
    setFullName(initialState.fullName);
    setIsAdmin(initialState.isAdmin);
    setIsActive(initialState.isActive);
    setPasswordChangeRequired(initialState.passwordChangeRequired);
    setErrors({});
  }, []);

  const handleSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>, onSuccess?: () => void) => {
      event.preventDefault();

      if (validateForm()) {
        try {
          // Form is valid, proceed with submission
          const formData = getFormData();

          // Call the API to create user
          await createUser(formData);

          // Call success callback if provided
          if (onSuccess) {
            onSuccess();
          }

          // Reset form after successful submission
          resetForm();
        } catch (error) {
          // Handle API errors from useQuery
          const fallbackMessage = intl.formatMessage({ id: "users.form.error.createFailed" });
          const errorMessage = parseApiError(error, fallbackMessage);
          setErrors({ submit: errorMessage });
        }
      }
    },
    [validateForm, getFormData, createUser, resetForm],
  );

  const isValid = useMemo(() => {
    if (!email.trim() || !password.trim() || !confirmPassword.trim()) return false;
    if (password !== confirmPassword) return false;
    // Basic email format check
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email.trim())) return false;
    // Password length check
    if (password.length < VALIDATION.MIN_PASSWORD_LENGTH) return false;
    return true;
  }, [email, password, confirmPassword]);

  return {
    // State
    email,
    password,
    confirmPassword,
    fullName,
    isAdmin,
    isActive,
    passwordChangeRequired,
    errors,
    isValid,
    isSubmitting,

    // Setters
    setEmail,
    setPassword,
    setConfirmPassword,
    setFullName,
    setIsAdmin,
    setIsActive,
    setPasswordChangeRequired,

    // Actions
    resetForm,
    validateForm,
    validateField,
    handleSubmit,
    getFormData,
  };
}
