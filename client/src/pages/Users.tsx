import { useCallback, useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { useIntl } from "react-intl";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { UserForm } from "@/components/users/UserForm";
import { UsersTable } from "@/components/users/UsersTable";
import { DeleteUserDialog } from "@/components/users/DeleteUserDialog";
import { useUsersList } from "@/hooks/useUsersList";
import { usersApi } from "@/api/users";
import { ApiError } from "@/api/client";
import type { User, CreateUserRequest, UpdateUserRequest } from "@/types/user";

const DEFAULT_PAGE_SIZE = 10;

// Backend error message constants (coupled to mcpgateway/routers/email_auth.py)
// TODO: Replace with structured error codes from API
const ERROR_MESSAGES = {
  CANNOT_DELETE_SELF: "own account",
  CANNOT_DELETE_LAST_ADMIN: "last remaining admin",
} as const;

export function Users() {
  const intl = useIntl();
  const [limit, setLimit] = useState(DEFAULT_PAGE_SIZE);
  const [allUsers, setAllUsers] = useState<User[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [userToEdit, setUserToEdit] = useState<User | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [userToDelete, setUserToDelete] = useState<User | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const {
    data: response,
    error: queryError,
    isLoading,
  } = useUsersList({ limit: DEFAULT_PAGE_SIZE });

  const {
    execute: executeLoadMore,
    isLoading: isLoadingMore,
    error: loadMoreError,
  } = useUsersList({ cursor: nextCursor ?? undefined, limit, enabled: false, immediate: false });

  useEffect(() => {
    if (response) {
      setAllUsers(response.users);
      setNextCursor(response.nextCursor ?? null);
    }
  }, [response]);

  useEffect(() => {
    if (loadMoreError) {
      console.error("Failed to load more users:", loadMoreError);
    }
  }, [loadMoreError]);

  const handleLoadMore = useCallback(async () => {
    if (!nextCursor || isLoadingMore) return;

    try {
      const result = await executeLoadMore();
      setAllUsers((prev) => [...prev, ...result.users]);
      setNextCursor(result.nextCursor ?? null);
    } catch {
      // Error already logged in useEffect
    }
  }, [nextCursor, isLoadingMore, executeLoadMore]);

  const handleLimitChange = useCallback((newLimit: number) => {
    setLimit(newLimit);
  }, []);

  const handleEditClick = useCallback((user: User) => {
    setUserToEdit(user);
    setIsFormOpen(true);
  }, []);

  const handleFormClose = useCallback(() => {
    setIsFormOpen(false);
    setUserToEdit(null);
  }, []);

  const handleDeleteClick = useCallback((user: User) => {
    setUserToDelete(user);
    setDeleteDialogOpen(true);
  }, []);

  const handleDeleteConfirm = useCallback(async () => {
    if (!userToDelete) return;

    setIsDeleting(true);

    // Optimistic update: remove from list immediately
    const previousUsers = allUsers;
    setAllUsers((prev) => prev.filter((u) => u.email !== userToDelete.email));

    try {
      await usersApi.delete(userToDelete.email);
      toast.success(
        intl.formatMessage({ id: "users.delete.success" }, { email: userToDelete.email }),
      );
      setDeleteDialogOpen(false);
      setUserToDelete(null);
    } catch (err) {
      // Rollback optimistic update
      setAllUsers(previousUsers);

      let errorMessage = intl.formatMessage(
        { id: "users.delete.error.generic" },
        { error: err instanceof Error ? err.message : "Unknown error" },
      );

      if (err instanceof ApiError) {
        if (err.status === 400) {
          const detail = (err.body as { detail?: string })?.detail || "";
          if (detail.includes(ERROR_MESSAGES.CANNOT_DELETE_SELF)) {
            errorMessage = intl.formatMessage({ id: "users.delete.error.self" });
          } else if (detail.includes(ERROR_MESSAGES.CANNOT_DELETE_LAST_ADMIN)) {
            errorMessage = intl.formatMessage({ id: "users.delete.error.lastAdmin" });
          }
        } else if (err.status === 404) {
          errorMessage = intl.formatMessage({ id: "users.delete.error.notFound" });
        }
      }

      toast.error(errorMessage);
    } finally {
      setIsDeleting(false);
    }
  }, [userToDelete, allUsers, intl]);

  const handleDeleteCancel = useCallback(() => {
    setDeleteDialogOpen(false);
    setUserToDelete(null);
  }, []);

  const error = queryError ? queryError.message : null;

  return (
    <main className="p-6">
      {isFormOpen ? (
        <UserForm
          isOpen={isFormOpen}
          onToggle={handleFormClose}
          user={userToEdit ?? undefined}
          onOptimisticCreate={(userData: CreateUserRequest | UpdateUserRequest) => {
            if ("email" in userData) {
              const optimisticUser: User = {
                email: userData.email,
                full_name: userData.full_name,
                is_admin: userData.is_admin ?? false,
                is_active: userData.is_active ?? true,
                auth_provider: "email",
                created_at: new Date().toISOString(),
                email_verified: false,
                password_change_required: userData.password_change_required ?? false,
                failed_login_attempts: 0,
                is_locked: false,
              };
              setAllUsers((prev) => [optimisticUser, ...prev]);
            }
          }}
          onSuccess={(result?: User) => {
            if (result) {
              setAllUsers((prev) => prev.map((u) => (u.email === result.email ? result : u)));
              toast.success(
                intl.formatMessage({ id: "users.edit.success" }, { email: result.email }),
              );
            }
            handleFormClose();
          }}
          onError={(userData: CreateUserRequest | UpdateUserRequest) => {
            if ("email" in userData) {
              setAllUsers((prev) => prev.filter((u) => u.email !== userData.email));
            }
          }}
        />
      ) : (
        <div className="space-y-6">
          <header className="flex items-center justify-between">
            <h1 className="text-xl font-semibold text-foreground">
              {intl.formatMessage({ id: "users.title" })}
            </h1>
            <Button
              onClick={() => setIsFormOpen(true)}
              className="gap-2"
              aria-label={intl.formatMessage({ id: "users.createUser" })}
            >
              <Plus className="h-4 w-4" aria-hidden="true" />
              {intl.formatMessage({ id: "users.createUser" })}
            </Button>
          </header>
          {isLoading ? (
            <div
              role="status"
              aria-live="polite"
              aria-busy="true"
              className="flex items-center justify-center p-12"
            >
              <span className="sr-only">{intl.formatMessage({ id: "users.loading.sr" })}</span>
              <div className="h-8 w-8 animate-spin rounded-full border-4 border-border border-t-primary" />
            </div>
          ) : (
            <>
              {error && (
                <div
                  className="mb-6 rounded-lg border border-destructive/20 bg-destructive/10 p-4"
                  role="alert"
                  aria-live="assertive"
                  aria-atomic="true"
                >
                  <h3 className="mb-1 font-semibold">
                    {intl.formatMessage({ id: "users.error.loading" })}
                  </h3>
                  <p className="text-destructive">{error}</p>
                </div>
              )}

              {allUsers.length > 0 ? (
                <>
                  <UsersTable
                    users={allUsers}
                    onDeleteClick={handleDeleteClick}
                    onEditClick={handleEditClick}
                  />

                  <div className="mt-6 flex items-center justify-between">
                    <div className="flex items-center gap-4">
                      <div className="text-sm text-muted-foreground">
                        {intl.formatMessage({ id: "users.showing" }, { count: allUsers.length })}
                      </div>
                      <div className="flex items-center gap-2">
                        <label
                          htmlFor="users-limit-select"
                          className="text-sm text-muted-foreground"
                        >
                          {intl.formatMessage({ id: "users.perPage" })}
                        </label>
                        <select
                          id="users-limit-select"
                          value={limit}
                          onChange={(event) => handleLimitChange(Number(event.target.value))}
                          className="rounded-md border border-input bg-background px-2 py-1 text-sm"
                        >
                          <option value={10}>10</option>
                          <option value={25}>25</option>
                          <option value={50}>50</option>
                          <option value={100}>100</option>
                        </select>
                      </div>
                    </div>
                    {nextCursor && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={handleLoadMore}
                        disabled={isLoadingMore}
                        aria-label={intl.formatMessage({ id: "users.loadMore.aria" })}
                      >
                        {isLoadingMore
                          ? intl.formatMessage({ id: "users.loadMore.loading" })
                          : intl.formatMessage({ id: "users.loadMore" })}
                      </Button>
                    )}
                  </div>
                </>
              ) : (
                <div className="rounded-2xl border border-border bg-card p-8 shadow-sm">
                  <h2 className="text-xl font-semibold text-card-foreground">
                    {intl.formatMessage({ id: "users.empty.title" })}
                  </h2>
                </div>
              )}
            </>
          )}
        </div>
      )}
      {userToDelete && (
        <DeleteUserDialog
          isOpen={deleteDialogOpen}
          userEmail={userToDelete.email}
          userName={userToDelete.full_name || userToDelete.email}
          onConfirm={handleDeleteConfirm}
          onCancel={handleDeleteCancel}
          isDeleting={isDeleting}
        />
      )}
    </main>
  );
}
