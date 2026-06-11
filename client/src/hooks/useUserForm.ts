import { useState, useCallback, useMemo, type FormEvent } from "react";
import { z } from "zod";
import { useIntl } from "react-intl";
import { useQuery } from "@/hooks/useQuery";
import { sanitizeString, sanitizePassword } from "@/lib/sanitize";
import { VALIDATION } from "@/lib/constants";
import { parseApiError } from "@/lib/errorUtils";
import type { User, CreateUserRequest, UpdateUserRequest } from "@/types/user";

// Fields shared by both create and edit schemas
const sharedUserFields = {
  fullName: z
    .string()
    .transform((val) => sanitizeString(val, VALIDATION.MAX_NAME_LENGTH))
    .optional(),
  isAdmin: z.boolean().default(false),
  isActive: z.boolean().default(true),
  passwordChangeRequired: z.boolean().default(false),
};

// Zod schema factory that accepts intl for localized messages
const createUserFormObjectSchema = (intl: ReturnType<typeof useIntl>) =>
  z.object({
    email: z
      .string()
      .transform((val) => sanitizeString(val, VALIDATION.MAX_EMAIL_LENGTH))
      .pipe(z.string().email(intl.formatMessage({ id: "users.form.error.emailInvalid" }))),
    password: z
      .string()
      .transform((val) => sanitizePassword(val, VALIDATION.MAX_PASSWORD_LENGTH))
      .pipe(
        z
          .string()
          .min(
            VALIDATION.MIN_PASSWORD_LENGTH,
            intl.formatMessage({ id: "users.form.error.passwordMinLength" }),
          ),
      ),
    confirmPassword: z.string(),
    ...sharedUserFields,
  });

const createUserFormSchema = (intl: ReturnType<typeof useIntl>) =>
  createUserFormObjectSchema(intl).refine(
    (data) => data.password === data.confirmPassword, // pragma: allowlist secret
    {
      message: intl.formatMessage({ id: "users.form.error.passwordsDoNotMatch" }),
      path: ["confirmPassword"],
    },
  );

const editUserFormSchema = (intl: ReturnType<typeof useIntl>) =>
  z
    .object({
      ...sharedUserFields,
      password: z
        .union([
          z
            .string()
            .min(1)
            .transform((val) => sanitizePassword(val, VALIDATION.MAX_PASSWORD_LENGTH))
            .pipe(
              z
                .string()
                .min(
                  VALIDATION.MIN_PASSWORD_LENGTH,
                  intl.formatMessage({ id: "users.form.error.passwordMinLength" }),
                ),
            ),
          z.literal(""),
        ])
        .optional(),
      confirmPassword: z.string().optional(),
    })
    .refine(
      (data) => !data.password || data.password === data.confirmPassword, // pragma: allowlist secret
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

export interface UseUserFormOptions {
  initialUser?: User;
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
  isEditMode: boolean;

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
  handleSubmit: (
    event: FormEvent<HTMLFormElement>,
    onSuccess?: (result?: User) => void,
    onOptimisticCreate?: (userData: CreateUserRequest) => void,
    onError?: (userData: CreateUserRequest | UpdateUserRequest) => void,
    onOptimisticUpdate?: (email: string, userData: UpdateUserRequest) => void,
  ) => Promise<void>;
  getFormData: () => CreateUserRequest | UpdateUserRequest;
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

export function useUserForm(options?: UseUserFormOptions): UseUserFormReturn {
  const intl = useIntl();
  const isEditMode = !!options?.initialUser;
  const initialUser = options?.initialUser;

  const [email, setEmail] = useState(initialUser?.email ?? initialState.email);
  const [password, setPassword] = useState(initialState.password);
  const [confirmPassword, setConfirmPassword] = useState(initialState.confirmPassword);
  const [fullName, setFullName] = useState(initialUser?.full_name ?? initialState.fullName);
  const [isAdmin, setIsAdmin] = useState(initialUser?.is_admin ?? initialState.isAdmin);
  const [isActive, setIsActive] = useState(initialUser?.is_active ?? initialState.isActive);
  const [passwordChangeRequired, setPasswordChangeRequired] = useState(
    initialUser?.password_change_required ?? initialState.passwordChangeRequired,
  );
  const [errors, setErrors] = useState<FormErrors>({});

  // Create localized schemas
  const userFormSchema = useMemo(() => createUserFormSchema(intl), [intl]);
  const editFormSchema = useMemo(() => editUserFormSchema(intl), [intl]);

  // Use useQuery for POST request to create user (create mode only)
  const { execute: createUser, isLoading: isCreating } = useQuery<User, CreateUserRequest>(
    "/auth/email/admin/users",
    {
      method: "POST",
      enabled: false, // Don't execute immediately
    },
  );

  // Use useQuery for PATCH request to update user (edit mode only)
  const { execute: updateUser, isLoading: isUpdating } = useQuery<User, UpdateUserRequest>(
    initialUser ? `/auth/email/admin/users/${encodeURIComponent(initialUser.email)}` : "",
    {
      method: "PATCH",
      enabled: false, // Don't execute immediately
    },
  );

  const getFormData = useCallback((): CreateUserRequest | UpdateUserRequest => {
    if (isEditMode) {
      const data: UpdateUserRequest = {
        full_name: fullName || undefined,
        is_admin: isAdmin,
        is_active: isActive,
        password_change_required: passwordChangeRequired,
      };
      if (password) {
        data.password = password; // pragma: allowlist secret
      }
      return data;
    }
    return {
      email,
      password,
      full_name: fullName || undefined,
      is_admin: isAdmin,
      is_active: isActive,
      password_change_required: passwordChangeRequired,
    };
  }, [email, password, fullName, isAdmin, isActive, passwordChangeRequired, isEditMode]);

  // Cache validation result to avoid redundant parsing
  const validationResult = useMemo((): z.ZodError | null => {
    const data = isEditMode
      ? { fullName, isAdmin, isActive, passwordChangeRequired, password, confirmPassword }
      : { email, password, confirmPassword, fullName, isAdmin, isActive, passwordChangeRequired };
    const result = isEditMode ? editFormSchema.safeParse(data) : userFormSchema.safeParse(data);
    return result.success ? null : result.error;
  }, [
    email,
    password,
    confirmPassword,
    fullName,
    isAdmin,
    isActive,
    passwordChangeRequired,
    userFormSchema,
    editFormSchema,
    isEditMode,
  ]);

  const validateField = useCallback(
    (field: keyof FormErrors, value: string | boolean) => {
      const currentData = isEditMode
        ? { fullName, isAdmin, isActive, passwordChangeRequired, password, confirmPassword }
        : { email, password, confirmPassword, fullName, isAdmin, isActive, passwordChangeRequired };
      const schema = isEditMode ? editFormSchema : userFormSchema;
      const result = schema.safeParse({ ...currentData, [field]: value });
      if (result.success) {
        setErrors((prev) => {
          const next = { ...prev };
          delete next[field];
          return next;
        });
      } else {
        const fieldIssue = result.error.issues.find((i) => i.path[0] === field);
        if (fieldIssue) {
          setErrors((prev) => ({ ...prev, [field]: fieldIssue.message }));
        } else {
          setErrors((prev) => {
            const next = { ...prev };
            delete next[field];
            return next;
          });
        }
      }
    },
    [
      email,
      password,
      confirmPassword,
      fullName,
      isAdmin,
      isActive,
      passwordChangeRequired,
      userFormSchema,
      editFormSchema,
      isEditMode,
    ],
  );

  const validateForm = useCallback((): boolean => {
    if (!validationResult) {
      setErrors({});
      return true;
    }
    const newErrors: FormErrors = {};
    validationResult.issues.forEach((issue) => {
      const path = issue.path[0] as keyof FormErrors;
      newErrors[path] = issue.message;
    });
    setErrors(newErrors);
    return false;
  }, [validationResult]);

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
    async (
      event: FormEvent<HTMLFormElement>,
      onSuccess?: (result?: User) => void,
      onOptimisticCreate?: (userData: CreateUserRequest) => void,
      onError?: (userData: CreateUserRequest | UpdateUserRequest) => void,
      onOptimisticUpdate?: (email: string, userData: UpdateUserRequest) => void,
    ) => {
      event.preventDefault();

      if (validateForm()) {
        const formData = getFormData();

        const reportError = (
          error: unknown,
          messageId: string,
          data: CreateUserRequest | UpdateUserRequest,
        ) => {
          onError?.(data);
          setErrors({ submit: parseApiError(error, intl.formatMessage({ id: messageId })) });
        };

        if (isEditMode && initialUser) {
          const updateData = formData as UpdateUserRequest;
          try {
            if (onOptimisticUpdate) {
              onOptimisticUpdate(initialUser.email, updateData);
            }
            const updated = await updateUser(updateData);
            if (onSuccess) {
              onSuccess(updated);
            }
          } catch (error) {
            reportError(error, "users.form.error.updateFailed", updateData);
          }
        } else {
          const createData = formData as CreateUserRequest;
          try {
            if (onOptimisticCreate) {
              onOptimisticCreate(createData);
            }
            await createUser(createData);
            if (onSuccess) {
              onSuccess();
            }
            resetForm();
          } catch (error) {
            reportError(error, "users.form.error.createFailed", createData);
          }
        }
      }
    },
    [validateForm, getFormData, createUser, updateUser, resetForm, intl, isEditMode, initialUser],
  );

  const isValid = useMemo(() => validationResult === null, [validationResult]);

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
    isSubmitting: isEditMode ? isUpdating : isCreating,
    isEditMode,

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
