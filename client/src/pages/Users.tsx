import { useCallback, useEffect, useMemo, useState } from "react";
import { Plus } from "lucide-react";
import { useIntl } from "react-intl";
import { Button } from "@/components/ui/button";
import { UserForm } from "@/components/users/UserForm";
import { UsersTable } from "@/components/users/UsersTable";
import { useQuery } from "@/hooks/useQuery";
import type { User, UsersResponse, CreateUserRequest } from "@/types/user";

const DEFAULT_PAGE_SIZE = 10;

export function Users() {
  const intl = useIntl();
  const [limit, setLimit] = useState(DEFAULT_PAGE_SIZE);
  const [allUsers, setAllUsers] = useState<User[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [isFormOpen, setIsFormOpen] = useState(false);

  const queryPath = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", DEFAULT_PAGE_SIZE.toString());
    params.set("include_pagination", "true");
    return `/auth/email/admin/users?${params.toString()}`;
  }, []);

  const { data: response, error: queryError, isLoading } = useQuery<UsersResponse>(queryPath);

  const loadMorePath = useMemo(() => {
    if (!nextCursor) return "";
    const params = new URLSearchParams();
    params.set("cursor", nextCursor);
    params.set("limit", limit.toString());
    params.set("include_pagination", "true");
    return `/auth/email/admin/users?${params.toString()}`;
  }, [nextCursor, limit]);

  const {
    execute: executeLoadMore,
    isLoading: isLoadingMore,
    error: loadMoreError,
  } = useQuery<UsersResponse>(loadMorePath || "/auth/email/admin/users", {
    enabled: false,
    immediate: false,
  });

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

  const error = queryError ? queryError.message : null;

  return (
    <main className="p-6">
      {isFormOpen ? (
        <UserForm
          isOpen={isFormOpen}
          onToggle={() => setIsFormOpen(false)}
          onOptimisticCreate={(userData: CreateUserRequest) => {
            // Create optimistic user object
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

            // Add to the beginning of the list
            setAllUsers((prev) => [optimisticUser, ...prev]);
          }}
          onSuccess={() => {
            setIsFormOpen(false);
          }}
          onError={(optimisticUser) => {
            // Rollback: remove the optimistic user by email
            if (optimisticUser) {
              setAllUsers((prev) => prev.filter((u) => u.email !== optimisticUser.email));
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
                  <UsersTable users={allUsers} />

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
    </main>
  );
}
