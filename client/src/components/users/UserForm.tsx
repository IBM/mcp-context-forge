import React from "react";
import { ChevronDown, User } from "lucide-react";
import { useIntl } from "react-intl";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { useUserForm } from "@/hooks/useUserForm";
import { PasswordInput } from "./PasswordInput";
import type { CreateUserRequest, UpdateUserRequest, User as UserType } from "@/types/user";

interface UserFormProps {
  isOpen: boolean;
  onToggle: () => void;
  user?: UserType;
  onSuccess?: (result?: UserType) => void;
  onOptimisticCreate?: (userData: CreateUserRequest | UpdateUserRequest) => void;
  onError?: (userData: CreateUserRequest | UpdateUserRequest) => void;
}

interface FormFieldProps {
  id: string;
  label: string;
  required?: boolean;
  error?: string;
  children: React.ReactNode;
}

function FormField({ id, label, required = false, error, children }: FormFieldProps) {
  return (
    <div className="space-y-1">
      <label
        htmlFor={id}
        className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
      >
        {label}
        {required && (
          <>
            <span className="text-red-500" aria-hidden="true">
              *
            </span>
            <span className="sr-only">(required)</span>
          </>
        )}
      </label>
      {children}
      {error && (
        <p id={`${id}-error`} className="text-sm text-red-600 dark:text-red-400" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

interface CheckboxFieldProps {
  id: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: string;
}

function CheckboxField({ id, checked, onCheckedChange, label }: CheckboxFieldProps) {
  return (
    <div className="flex items-center space-x-2">
      <Checkbox
        id={id}
        checked={checked}
        onCheckedChange={(value) => onCheckedChange(value === true)}
      />
      <label
        htmlFor={id}
        className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
      >
        {label}
      </label>
    </div>
  );
}

export function UserForm({
  isOpen,
  onToggle,
  user,
  onSuccess,
  onOptimisticCreate,
  onError,
}: UserFormProps) {
  const intl = useIntl();
  const {
    email,
    password,
    confirmPassword,
    fullName,
    isAdmin,
    isActive,
    passwordChangeRequired,
    errors,
    isSubmitting,
    isEditMode,
    setEmail,
    setPassword,
    setConfirmPassword,
    setFullName,
    setIsAdmin,
    setIsActive,
    setPasswordChangeRequired,
    handleSubmit,
  } = useUserForm({ initialUser: user });

  const [advancedOpen, setAdvancedOpen] = React.useState(isEditMode);

  const onSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    handleSubmit(
      event,
      (result?: UserType) => {
        if (onSuccess) {
          onSuccess(result);
        } else {
          onToggle();
        }
      },
      onOptimisticCreate,
      onError,
    );
  };

  if (!isOpen) return null;

  return (
    <>
      <div className="mx-auto mt-6 w-full max-w-3xl rounded-xl border border-neutral-200 bg-inherit p-0 shadow-[0_12px_40px_rgba(15,23,42,0.12)] dark:border-neutral-800">
        <div className="flex flex-col gap-8 p-6 sm:p-8">
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-sm bg-blue-500 text-white shadow-sm">
                <User className="h-5 w-5" />
              </div>
              <h2
                id="user-form-title"
                className="text-2xl font-semibold tracking-tight text-neutral-950 dark:text-neutral-50"
              >
                {intl.formatMessage({
                  id: isEditMode ? "users.edit.dialog.title" : "users.form.title",
                })}
              </h2>
            </div>

            <p className="text-sm leading-6 text-neutral-600 dark:text-neutral-400">
              {isEditMode && user
                ? intl.formatMessage({ id: "users.edit.dialog.description" }, { email: user.email })
                : intl.formatMessage({ id: "users.form.description" })}
            </p>
          </div>

          <form className="space-y-6" onSubmit={onSubmit} aria-labelledby="user-form-title">
            <div className="space-y-1">
              {isEditMode ? (
                <>
                  <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100">
                    {intl.formatMessage({ id: "users.form.email" })}
                  </p>
                  <p className="rounded-md border border-neutral-200 bg-neutral-50 px-4 py-2 text-sm text-neutral-600 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-400">
                    {user?.email}
                  </p>
                </>
              ) : (
                <FormField
                  id="user-email"
                  label={intl.formatMessage({ id: "users.form.email" })}
                  required
                  error={errors.email}
                >
                  <Input
                    id="user-email"
                    type="email"
                    autoComplete="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    placeholder={intl.formatMessage({ id: "users.form.email.placeholder" })}
                    className="rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
                    aria-invalid={!!errors.email}
                    aria-describedby={errors.email ? "user-email-error" : undefined}
                  />
                </FormField>
              )}
            </div>

            <FormField
              id="user-full-name"
              label={intl.formatMessage({ id: "users.form.fullName" })}
              error={errors.fullName}
            >
              <Input
                id="user-full-name"
                type="text"
                autoComplete="name"
                value={fullName}
                onChange={(event) => setFullName(event.target.value)}
                placeholder={intl.formatMessage({ id: "users.form.fullName.placeholder" })}
                className="rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
                aria-invalid={!!errors.fullName}
                aria-describedby={errors.fullName ? "user-full-name-error" : undefined}
              />
            </FormField>

            <PasswordInput
              id="user-password"
              value={password}
              onChange={setPassword}
              label={intl.formatMessage({ id: "users.form.password" })}
              required={!isEditMode}
              placeholder={intl.formatMessage({
                id: isEditMode
                  ? "users.form.password.optional.placeholder"
                  : "users.form.password.placeholder",
              })}
              error={errors.password}
              hint={
                isEditMode ? intl.formatMessage({ id: "users.form.password.optional" }) : undefined
              }
            />

            {(!isEditMode || password) && (
              <PasswordInput
                id="user-confirm-password"
                value={confirmPassword}
                onChange={setConfirmPassword}
                label={intl.formatMessage({ id: "users.form.confirmPassword" })}
                required
                placeholder={intl.formatMessage({ id: "users.form.confirmPassword.placeholder" })}
                error={errors.confirmPassword}
              />
            )}

            <div className="flex flex-col gap-5 pt-2">
              <button
                type="button"
                onClick={() => setAdvancedOpen((current) => !current)}
                className="inline-flex w-full items-center gap-2 rounded-md border border-neutral-200 px-3 py-2 text-sm font-medium text-neutral-600 transition hover:text-neutral-950 dark:border-neutral-800 dark:text-neutral-400 dark:hover:text-neutral-300"
                aria-expanded={advancedOpen}
                aria-controls="advanced-settings-region"
              >
                <ChevronDown
                  className={`h-4 w-4 transition ${advancedOpen ? "rotate-180" : ""}`}
                  aria-hidden="true"
                />
                {intl.formatMessage({ id: "users.form.advancedSettings" })}
              </button>

              {advancedOpen && (
                <div
                  id="advanced-settings-region"
                  role="region"
                  aria-labelledby="advanced-settings-label"
                  className="space-y-4 rounded-md border border-neutral-200 p-4 dark:border-neutral-800"
                >
                  <span id="advanced-settings-label" className="sr-only">
                    {intl.formatMessage({ id: "users.form.advancedSettings" })}
                  </span>
                  <fieldset className="space-y-4">
                    <legend className="sr-only">User Permissions and Settings</legend>
                    <CheckboxField
                      id="user-is-admin"
                      checked={isAdmin}
                      onCheckedChange={setIsAdmin}
                      label={intl.formatMessage({ id: "users.form.isAdmin" })}
                    />
                    <CheckboxField
                      id="user-is-active"
                      checked={isActive}
                      onCheckedChange={setIsActive}
                      label={intl.formatMessage({ id: "users.form.isActive" })}
                    />
                    <CheckboxField
                      id="user-password-change-required"
                      checked={passwordChangeRequired}
                      onCheckedChange={setPasswordChangeRequired}
                      label={intl.formatMessage({ id: "users.form.passwordChangeRequired" })}
                    />
                  </fieldset>
                </div>
              )}

              {errors.submit && (
                <div
                  className="rounded-md border border-red-200 bg-red-50 p-3 dark:border-red-900/50 dark:bg-red-950/50"
                  role="alert"
                  aria-live="assertive"
                >
                  <p className="text-sm text-red-700 dark:text-red-300">{errors.submit}</p>
                </div>
              )}

              <div className="flex items-center justify-end gap-3 pt-6">
                <Button
                  type="button"
                  variant="ghost"
                  onClick={onToggle}
                  className="h-10 rounded-md px-3 text-sm font-medium text-neutral-700 hover:bg-neutral-100 hover:text-neutral-950 dark:text-neutral-300 dark:hover:bg-neutral-800 dark:hover:text-neutral-100"
                >
                  {intl.formatMessage({ id: "users.form.button.cancel" })}
                </Button>
                <Button
                  type="submit"
                  disabled={isSubmitting}
                  className="h-10 rounded-md bg-neutral-950 px-4 text-sm font-medium text-white hover:enabled:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-950 dark:hover:enabled:bg-neutral-200"
                >
                  {isSubmitting
                    ? intl.formatMessage({
                        id: isEditMode ? "users.form.button.saving" : "users.form.button.creating",
                      })
                    : intl.formatMessage({
                        id: isEditMode ? "users.form.button.save" : "users.form.button.create",
                      })}
                </Button>
              </div>
            </div>
          </form>
        </div>
      </div>
    </>
  );
}
