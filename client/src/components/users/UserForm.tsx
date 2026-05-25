import React from "react";
import { ChevronDown, User } from "lucide-react";
import { useIntl } from "react-intl";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { useUserForm } from "@/hooks/useUserForm";
import type { CreateUserRequest } from "@/types/user";

interface UserFormProps {
  isOpen: boolean;
  onToggle: () => void;
  onSuccess?: () => void;
  onOptimisticCreate?: (userData: CreateUserRequest) => void;
  onError?: (userData: CreateUserRequest) => void;
}

export function UserForm({
  isOpen,
  onToggle,
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
    setEmail,
    setPassword,
    setConfirmPassword,
    setFullName,
    setIsAdmin,
    setIsActive,
    setPasswordChangeRequired,
    handleSubmit,
  } = useUserForm();

  const [advancedOpen, setAdvancedOpen] = React.useState(false);

  const onSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    handleSubmit(
      event,
      () => {
        // Success callback
        if (onSuccess) {
          onSuccess();
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
                {intl.formatMessage({ id: "users.form.title" })}
              </h2>
            </div>

            <p className="text-sm leading-6 text-neutral-600 dark:text-neutral-400">
              {intl.formatMessage({ id: "users.form.description" })}
            </p>
          </div>

          <form className="space-y-6" onSubmit={onSubmit} aria-labelledby="user-form-title">
            <div className="space-y-1">
              <label
                htmlFor="user-email"
                className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
              >
                {intl.formatMessage({ id: "users.form.email" })}
                <span className="text-red-500">*</span>
                <span className="sr-only">(required)</span>
              </label>
              <Input
                id="user-email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder={intl.formatMessage({ id: "users.form.email.placeholder" })}
                className="rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
                aria-invalid={!!errors.email}
                aria-describedby={errors.email ? "email-error" : undefined}
              />
              {errors.email && (
                <p
                  id="email-error"
                  className="text-sm text-red-600 dark:text-red-400"
                  role="alert"
                  aria-live="polite"
                >
                  {errors.email}
                </p>
              )}
            </div>

            <div className="space-y-1">
              <label
                htmlFor="user-password"
                className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
              >
                {intl.formatMessage({ id: "users.form.password" })}
                <span className="text-red-500">*</span>
                <span className="sr-only">(required)</span>
              </label>
              <Input
                id="user-password"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder={intl.formatMessage({ id: "users.form.password.placeholder" })}
                className="rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
                aria-invalid={!!errors.password}
                aria-describedby={errors.password ? "password-error" : undefined}
              />
              {errors.password && (
                <p
                  id="password-error"
                  className="text-sm text-red-600 dark:text-red-400"
                  role="alert"
                  aria-live="polite"
                >
                  {errors.password}
                </p>
              )}
            </div>

            <div className="space-y-1">
              <label
                htmlFor="user-confirm-password"
                className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
              >
                {intl.formatMessage({ id: "users.form.confirmPassword" })}
                <span className="text-red-500">*</span>
                <span className="sr-only">(required)</span>
              </label>
              <Input
                id="user-confirm-password"
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                placeholder={intl.formatMessage({ id: "users.form.confirmPassword.placeholder" })}
                className="rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
                aria-invalid={!!errors.confirmPassword}
                aria-describedby={errors.confirmPassword ? "confirm-password-error" : undefined}
              />
              {errors.confirmPassword && (
                <p
                  id="confirm-password-error"
                  className="text-sm text-red-600 dark:text-red-400"
                  role="alert"
                  aria-live="polite"
                >
                  {errors.confirmPassword}
                </p>
              )}
            </div>

            <div className="space-y-1">
              <label
                htmlFor="user-full-name"
                className="text-sm font-medium text-neutral-900 dark:text-neutral-100"
              >
                {intl.formatMessage({ id: "users.form.fullName" })}
              </label>
              <Input
                id="user-full-name"
                type="text"
                autoComplete="name"
                value={fullName}
                onChange={(event) => setFullName(event.target.value)}
                placeholder={intl.formatMessage({ id: "users.form.fullName.placeholder" })}
                className="rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
                aria-invalid={!!errors.fullName}
                aria-describedby={errors.fullName ? "full-name-error" : undefined}
              />
              {errors.fullName && (
                <p
                  id="full-name-error"
                  className="text-sm text-red-600 dark:text-red-400"
                  role="alert"
                  aria-live="polite"
                >
                  {errors.fullName}
                </p>
              )}
            </div>

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
                    <div className="flex items-center space-x-2">
                      <Checkbox
                        id="user-is-admin"
                        checked={isAdmin}
                        onCheckedChange={(checked) => setIsAdmin(checked === true)}
                      />
                      <label
                        htmlFor="user-is-admin"
                        className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
                      >
                        {intl.formatMessage({ id: "users.form.isAdmin" })}
                      </label>
                    </div>

                    <div className="flex items-center space-x-2">
                      <Checkbox
                        id="user-is-active"
                        checked={isActive}
                        onCheckedChange={(checked) => setIsActive(checked === true)}
                      />
                      <label
                        htmlFor="user-is-active"
                        className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
                      >
                        {intl.formatMessage({ id: "users.form.isActive" })}
                      </label>
                    </div>

                    <div className="flex items-center space-x-2">
                      <Checkbox
                        id="user-password-change-required"
                        checked={passwordChangeRequired}
                        onCheckedChange={(checked) => setPasswordChangeRequired(checked === true)}
                      />
                      <label
                        htmlFor="user-password-change-required"
                        className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
                      >
                        {intl.formatMessage({ id: "users.form.passwordChangeRequired" })}
                      </label>
                    </div>
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
                    ? intl.formatMessage({ id: "users.form.button.creating" })
                    : intl.formatMessage({ id: "users.form.button.create" })}
                </Button>
              </div>
            </div>
          </form>
        </div>
      </div>
    </>
  );
}
