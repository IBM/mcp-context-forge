import { useCallback, useMemo, useState, type KeyboardEvent } from "react";
import { Search, SlidersHorizontal } from "lucide-react";
import { useIntl } from "react-intl";

import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useRecentActivity } from "@/hooks/useRecentActivity";
import { cn } from "@/lib/utils";
import type { ActivityItem, ActivityStatus } from "@/types/activity";

import { RecentActivityItem } from "./RecentActivityItem";

type ActivityTab = "all" | "alerts";

const TABS: Array<{ value: ActivityTab; labelId: string }> = [
  { value: "all", labelId: "dashboard.recentActivity.tabs.all" },
  { value: "alerts", labelId: "dashboard.recentActivity.tabs.alerts" },
];

const ALERT_STATUSES: ReadonlySet<ActivityStatus> = new Set(["error", "warning"]);

const INITIAL_VISIBLE = 10;
const EXPANDED_VISIBLE = 50;

function applyFilters(items: ActivityItem[], tab: ActivityTab, query: string): ActivityItem[] {
  let result = items;

  if (tab === "alerts") {
    result = result.filter((item) => ALERT_STATUSES.has(item.status));
  }

  const trimmed = query.trim().toLowerCase();
  if (trimmed.length > 0) {
    result = result.filter((item) => {
      return (
        item.title.toLowerCase().includes(trimmed) ||
        item.description.toLowerCase().includes(trimmed) ||
        item.actor.toLowerCase().includes(trimmed) ||
        item.resource_name.toLowerCase().includes(trimmed)
      );
    });
  }

  return result;
}

export function RecentActivity() {
  const intl = useIntl();
  const { items, isLoading, error, refetch } = useRecentActivity();

  const [activeTab, setActiveTab] = useState<ActivityTab>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [visibleCount, setVisibleCount] = useState<number>(INITIAL_VISIBLE);

  const filtered = useMemo(
    () => applyFilters(items, activeTab, searchQuery),
    [items, activeTab, searchQuery],
  );

  const visibleItems = filtered.slice(0, visibleCount);
  const hasMore = filtered.length > visibleCount;

  const handleTabKeyDown = useCallback(
    (e: KeyboardEvent<HTMLButtonElement>, currentValue: ActivityTab) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      e.preventDefault();
      const currentIndex = TABS.findIndex((t) => t.value === currentValue);
      const nextIndex =
        e.key === "ArrowRight"
          ? (currentIndex + 1) % TABS.length
          : (currentIndex - 1 + TABS.length) % TABS.length;
      const nextTab = TABS[nextIndex];
      setActiveTab(nextTab.value);
      document.getElementById(`recent-activity-tab-${nextTab.value}`)?.focus();
    },
    [],
  );

  return (
    <Card aria-labelledby="recent-activity-heading">
      <CardHeader>
        <CardTitle id="recent-activity-heading">
          {intl.formatMessage({ id: "dashboard.recentActivity.title" })}
        </CardTitle>
        <CardAction />
      </CardHeader>

      <CardContent className="flex flex-col gap-4">
        <div className="flex items-center justify-between gap-4">
          <div
            role="tablist"
            aria-label={intl.formatMessage({ id: "dashboard.recentActivity.tabs.ariaLabel" })}
            className="flex items-center gap-4 rounded-md bg-muted/50 p-1"
          >
            {TABS.map((tab) => (
              <button
                key={tab.value}
                id={`recent-activity-tab-${tab.value}`}
                type="button"
                role="tab"
                aria-selected={activeTab === tab.value}
                tabIndex={activeTab === tab.value ? 0 : -1}
                className={cn(
                  "rounded px-3 py-1 text-sm font-medium transition-colors",
                  activeTab === tab.value
                    ? "bg-background text-foreground shadow-xs"
                    : "text-muted-foreground hover:text-foreground",
                )}
                onClick={() => setActiveTab(tab.value)}
                onKeyDown={(e) => handleTabKeyDown(e, tab.value)}
              >
                {intl.formatMessage({ id: tab.labelId })}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <div className="relative">
              <Search
                aria-hidden="true"
                className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
              />
              <Input
                type="search"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={intl.formatMessage({
                  id: "dashboard.recentActivity.search.placeholder",
                })}
                aria-label={intl.formatMessage({
                  id: "dashboard.recentActivity.search.ariaLabel",
                })}
                className="h-8 w-56 pl-8 text-sm"
              />
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={intl.formatMessage({
                id: "dashboard.recentActivity.filter.ariaLabel",
              })}
              // TODO: wire a filter popover (status + source) once the popover primitive is available.
              disabled
            >
              <SlidersHorizontal className="size-4" aria-hidden="true" />
            </Button>
          </div>
        </div>

        <div
          role="tabpanel"
          aria-labelledby={`recent-activity-tab-${activeTab}`}
          className="flex flex-col gap-2"
        >
          {isLoading &&
            Array.from({ length: 5 }).map((_, index) => (
              <Skeleton key={index} className="h-14 w-full" data-testid="activity-skeleton" />
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
            <p className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
              {intl.formatMessage({ id: "dashboard.recentActivity.empty" })}
            </p>
          )}

          {!isLoading &&
            !error &&
            visibleItems.map((item) => <RecentActivityItem key={item.id} item={item} />)}
        </div>

        {!isLoading && !error && hasMore && (
          <div className="flex justify-center">
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
