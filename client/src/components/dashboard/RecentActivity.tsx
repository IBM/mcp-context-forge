/**
 * RecentActivity — the activity feed body for the V2 home (#5531).
 *
 * The view title ("Activity feed") and the Clear control are rendered by the
 * page's NonDefaultState header, so this renders only the feed body: the
 * Errors/Warnings severity filters (with live counts), a collapsible search, the
 * item list, and a "view more" control.
 *
 * Reuses the locked #5129 data contract: useRecentActivity, ActivityItem, the
 * status->icon lookup (in RecentActivityItem), the MSW handler, and the
 * dashboard.recentActivity.* i18n. Runs against the mock (VITE_USE_MOCK_ACTIVITY)
 * until GET /api/logs/activity (#5944) ships; no component change needed then.
 */

import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { useIntl } from "react-intl";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useRecentActivity } from "@/hooks/useRecentActivity";
import { cn } from "@/lib/utils";
import type { ActivityItem } from "@/types/activity";

import { RecentActivityItem } from "./RecentActivityItem";

type ActivityFilter = "all" | "error" | "warning";

const INITIAL_VISIBLE = 10;
const EXPANDED_VISIBLE = 50;

function applyFilters(
  items: ActivityItem[],
  filter: ActivityFilter,
  query: string,
): ActivityItem[] {
  let result = items;

  if (filter !== "all") {
    result = result.filter((item) => item.status === filter);
  }

  const trimmed = query.trim().toLowerCase();
  if (trimmed.length > 0) {
    result = result.filter(
      (item) =>
        item.title.toLowerCase().includes(trimmed) ||
        item.description.toLowerCase().includes(trimmed) ||
        item.actor.toLowerCase().includes(trimmed) ||
        item.resource_name.toLowerCase().includes(trimmed),
    );
  }

  return result;
}

export function RecentActivity() {
  const intl = useIntl();
  const { items, isLoading, error, refetch } = useRecentActivity();

  const [filter, setFilter] = useState<ActivityFilter>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [visibleCount, setVisibleCount] = useState<number>(INITIAL_VISIBLE);

  const errorCount = useMemo(() => items.filter((i) => i.status === "error").length, [items]);
  const warningCount = useMemo(() => items.filter((i) => i.status === "warning").length, [items]);

  const filtered = useMemo(
    () => applyFilters(items, filter, searchQuery),
    [items, filter, searchQuery],
  );
  const visibleItems = filtered.slice(0, visibleCount);
  const hasMore = filtered.length > visibleCount;

  // Single-select: "All activity" is the default and the way back after filtering.
  const filters: Array<{ value: ActivityFilter; labelId: string; count?: number }> = [
    { value: "all", labelId: "dashboard.recentActivity.filters.all" },
    { value: "error", labelId: "dashboard.recentActivity.filters.errors", count: errorCount },
    { value: "warning", labelId: "dashboard.recentActivity.filters.warnings", count: warningCount },
  ];

  return (
    <Card aria-label={intl.formatMessage({ id: "dashboard.recentActivity.title" })}>
      <CardContent className="flex flex-col gap-3">
        {/* Hide the filter/search toolbar in the error state: nothing to filter. */}
        {!error && (
          <div className="flex items-center justify-between gap-4 border-b border-border/60 pb-3">
            <div className="flex items-center gap-1">
              {filters.map((option) => {
                const active = filter === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    aria-pressed={active}
                    onClick={() => setFilter(option.value)}
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded px-2 py-1 text-sm transition-colors",
                      active
                        ? "bg-muted text-foreground"
                        : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {intl.formatMessage({ id: option.labelId })}
                    {option.count !== undefined ? (
                      <span className="tabular-nums text-muted-foreground">{option.count}</span>
                    ) : null}
                  </button>
                );
              })}
            </div>

            <div className="flex items-center gap-1">
              {searchOpen ? (
                <Input
                  type="search"
                  autoFocus
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onBlur={() => {
                    if (searchQuery.trim().length === 0) setSearchOpen(false);
                  }}
                  placeholder={intl.formatMessage({
                    id: "dashboard.recentActivity.search.placeholder",
                  })}
                  aria-label={intl.formatMessage({
                    id: "dashboard.recentActivity.search.ariaLabel",
                  })}
                  className="h-8 w-56 text-sm"
                />
              ) : (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label={intl.formatMessage({
                    id: "dashboard.recentActivity.search.ariaLabel",
                  })}
                  onClick={() => setSearchOpen(true)}
                >
                  <Search className="size-4" aria-hidden="true" />
                </Button>
              )}
            </div>
          </div>
        )}

        <div className="flex flex-col">
          {isLoading &&
            Array.from({ length: 5 }).map((_, index) => (
              <Skeleton
                key={index}
                className="my-1.5 h-12 w-full"
                data-testid="activity-skeleton"
              />
            ))}

          {!isLoading && error && (
            <div
              role="alert"
              className="flex flex-col items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
            >
              <span>
                {intl.formatMessage({ id: "dashboard.recentActivity.error" })} {error.message}
              </span>
              <Button type="button" variant="outline" size="sm" onClick={() => void refetch()}>
                {intl.formatMessage({ id: "dashboard.recentActivity.retry" })}
              </Button>
            </div>
          )}

          {!isLoading && !error && visibleItems.length === 0 && (
            <p className="p-6 text-center text-sm text-muted-foreground">
              {intl.formatMessage({ id: "dashboard.recentActivity.empty" })}
            </p>
          )}

          {!isLoading &&
            !error &&
            visibleItems.map((item) => <RecentActivityItem key={item.id} item={item} />)}
        </div>

        {!isLoading && !error && hasMore && (
          <div className="flex justify-center pt-1">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setVisibleCount(EXPANDED_VISIBLE)}
            >
              {intl.formatMessage({ id: "dashboard.recentActivity.viewMore" })}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
