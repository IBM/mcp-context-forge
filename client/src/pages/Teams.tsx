import { useState, useCallback, useMemo, useEffect } from "react";
import { useIntl } from "react-intl";
import { toast } from "sonner";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { TeamsTable } from "@/components/teams/TeamsTable";
import { useQuery } from "@/hooks/useQuery";
import { api } from "@/api/client";
import type { Team, TeamsResponse } from "@/types/team";

// Pagination constants
const DEFAULT_PAGE_SIZE = 10;

export function Teams() {
  const intl = useIntl();
  const [limit, setLimit] = useState(DEFAULT_PAGE_SIZE);
  const [allTeams, setAllTeams] = useState<Team[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  // Keep the primary list in sync with the selected page size
  const queryPath = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", limit.toString());
    return `/teams?${params.toString()}`;
  }, [limit]);

  // Use useQuery hook for initial data fetching and limit changes
  const { data: response, error: queryError, isLoading } = useQuery<TeamsResponse>(queryPath);

  useEffect(() => {
    if (response) {
      setAllTeams(response.teams);
      setNextCursor(response.nextCursor ?? null);
    }
  }, [response]);

  const teams = allTeams;

  // Convert query error to string for display
  const error = queryError ? queryError.message : null;

  const handleLoadMore = useCallback(async () => {
    if (!nextCursor || loadingMore) return;

    setLoadingMore(true);
    try {
      const params = new URLSearchParams();
      params.set("cursor", nextCursor);
      params.set("limit", limit.toString());

      const result = await api.get<TeamsResponse>(`/teams?${params.toString()}`);
      setAllTeams((prev) => [...prev, ...result.teams]);
      setNextCursor(result.nextCursor ?? null);
    } catch {
      toast.error(intl.formatMessage({ id: "teams.error.loadMore" }));
    } finally {
      setLoadingMore(false);
    }
  }, [nextCursor, limit, loadingMore]);

  const handleLimitChange = useCallback((newLimit: number) => {
    setLimit(newLimit);
  }, []);

  return (
    <div className="p-6">
      {isLoading ? (
        <div
          role="status"
          aria-live="polite"
          aria-busy="true"
          className="flex items-center justify-center p-12"
        >
          <span className="sr-only">{intl.formatMessage({ id: "teams.loading.sr" })}</span>
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-border border-t-primary" />
        </div>
      ) : (
        <>
          {error && (
            <div
              className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 mb-6"
              role="alert"
              aria-live="assertive"
              aria-atomic="true"
            >
              <h3 className="font-semibold mb-1">
                {intl.formatMessage({ id: "teams.error.loading" })}
              </h3>
              <p className="text-red-800 dark:text-red-200">{error}</p>
            </div>
          )}

          {teams.length > 0 ? (
            <>
              <div className="flex justify-between items-center mb-6">
                <h1 className="text-base font-semibold text-foreground">
                  {intl.formatMessage({ id: "teams.all.title" })}
                </h1>
                <Button
                  variant="default"
                  className="h-7 rounded-sm px-4"
                  onClick={() => {
                    // TODO: Open create team form
                  }}
                >
                  <Plus className="h-4 w-4" />
                  {intl.formatMessage({ id: "teams.createTeam" })}
                </Button>
              </div>

              <TeamsTable teams={teams} isLoading={isLoading} />

              <div className="flex items-center justify-between mt-6">
                <div className="flex items-center gap-4">
                  <div className="text-sm text-gray-600 dark:text-gray-400">
                    {intl.formatMessage({ id: "teams.showing" }, { count: teams.length })}
                  </div>
                  <div className="flex items-center gap-2">
                    <label
                      htmlFor="limit-select"
                      className="text-sm text-gray-600 dark:text-gray-400"
                    >
                      {intl.formatMessage({ id: "teams.perPage" })}
                    </label>
                    <select
                      id="limit-select"
                      value={limit}
                      onChange={(e) => handleLimitChange(Number(e.target.value))}
                      className="rounded-md border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1 text-sm"
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
                    disabled={loadingMore}
                    aria-label={intl.formatMessage({ id: "teams.loadMore.aria" })}
                  >
                    {loadingMore
                      ? intl.formatMessage({ id: "teams.loadMore.loading" })
                      : intl.formatMessage({ id: "teams.loadMore" })}
                  </Button>
                )}
              </div>
            </>
          ) : (
            <div className="border border-border rounded-lg p-6 flex flex-col gap-2">
              <h2 className="text-base font-medium">
                {intl.formatMessage({ id: "teams.empty.title" })}
              </h2>
              <div className="py-5">
                <p className="text-sm text-foreground">
                  {intl.formatMessage({ id: "teams.empty.description" })}
                </p>
              </div>
              <Button
                className="bg-foreground text-background hover:bg-foreground/90 h-8 w-38 rounded-sm px-2 gap-1.5 text-sm font-medium"
                onClick={() => {
                  // TODO: Open create team form
                }}
              >
                <Plus className="size-3" />
                {intl.formatMessage({ id: "teams.createTeam" })}
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
