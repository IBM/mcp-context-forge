import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent as ReactKeyboardEvent } from "react";
import { Search } from "lucide-react";
import { useIntl } from "react-intl";
import { searchAdminEntities } from "@/api/search";
import type { GlobalSearchGroup, GlobalSearchItem, SearchEntityType } from "@/api/search";
import { useAuthContext } from "@/auth/AuthContext";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { useRouter } from "@/router";
import { Input } from "../ui/input";
import { Button } from "@/components/ui/button";
import { Loading } from "@/components/ui/loading";
import { Popover, PopoverAnchor, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Separator } from "@/components/ui/separator";

const SEARCH_DEBOUNCE_MS = 250;
const MIN_QUERY_LENGTH = 2;
const SEARCH_LIMIT_PER_TYPE = 8;

const BASE_SEARCH_ENTITY_TYPES: SearchEntityType[] = [
  "servers",
  "gateways",
  "tools",
  "resources",
  "prompts",
  "agents",
  "teams",
];

const ENTITY_ROUTE: Record<SearchEntityType, string> = {
  servers: "/app/gateways",
  gateways: "/app/servers",
  tools: "/app/tools",
  resources: "/app/resources",
  prompts: "/app/prompts",
  agents: "/app/agents",
  teams: "/app/teams",
  users: "/app/users",
};

const ENTITY_LABEL_KEY: Record<SearchEntityType, string> = {
  servers: "navigation.virtualServers",
  gateways: "navigation.servers",
  tools: "navigation.tools",
  resources: "navigation.resources",
  prompts: "navigation.prompts",
  agents: "navigation.agents",
  teams: "navigation.teams",
  users: "navigation.users",
};

type SearchStatus = "idle" | "loading" | "success" | "error";

interface VisibleSearchItem {
  id: string;
  name: string;
  summary: string;
}

interface VisibleSearchGroup {
  entity_type: SearchEntityType;
  items: VisibleSearchItem[];
}

interface VisibleSearchResult {
  entityType: SearchEntityType;
  item: VisibleSearchItem;
}

type ShortcutNavigator = Pick<Navigator, "platform" | "userAgent"> & {
  userAgentData?: {
    platform?: string;
  };
};

export function getQuickNavShortcutLabel(nav: ShortcutNavigator = navigator) {
  const detectedPlatform = [nav.userAgentData?.platform, nav.platform, nav.userAgent]
    .filter(Boolean)
    .join(" ");

  return /mac|iphone|ipad|ipod/i.test(detectedPlatform) ? "⌘ K" : "Ctrl K";
}

function getString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function getItemId(item: GlobalSearchItem): string {
  return (
    getString(item.id) ||
    getString(item.email) ||
    getString(item.slug) ||
    getString(item.uri) ||
    getString(item.name)
  );
}

function getItemName(item: GlobalSearchItem): string {
  return (
    getString(item.display_name) ||
    getString(item.displayName) ||
    getString(item.original_name) ||
    getString(item.originalName) ||
    getString(item.name) ||
    getString(item.full_name) ||
    getString(item.email) ||
    getString(item.slug) ||
    getString(item.id) ||
    getString(item.uri)
  );
}

function getItemSummary(item: GlobalSearchItem): string {
  return (
    getString(item.description) ||
    getString(item.email) ||
    getString(item.slug) ||
    getString(item.url) ||
    getString(item.endpoint_url) ||
    getString(item.uri) ||
    getString(item.original_name) ||
    getString(item.id)
  );
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export function HeaderQuickNav() {
  const intl = useIntl();
  const { navigate } = useRouter();
  const { selectedTeamId, user } = useAuthContext();
  const [query, setQuery] = useState("");
  const [shortcutLabel, setShortcutLabel] = useState("Ctrl K");
  const [isExpanded, setIsExpanded] = useState(false);
  const [isPopoverOpen, setIsPopoverOpen] = useState(false);
  const [status, setStatus] = useState<SearchStatus>("idle");
  const [groups, setGroups] = useState<GlobalSearchGroup[]>([]);
  const [focusedResultIndex, setFocusedResultIndex] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);

  const trimmedQuery = query.trim();
  const isPlatformAdmin = Boolean(user?.is_admin);
  const searchEntityTypes = useMemo<SearchEntityType[]>(
    () => (isPlatformAdmin ? [...BASE_SEARCH_ENTITY_TYPES, "users"] : BASE_SEARCH_ENTITY_TYPES),
    [isPlatformAdmin],
  );
  const visibleGroups = useMemo<VisibleSearchGroup[]>(
    () =>
      groups
        .map((group) => ({
          entity_type: group.entity_type,
          items: group.items
            .map((item) => ({
              id: getItemId(item),
              name: getItemName(item),
              summary: getItemSummary(item),
            }))
            .filter((item) => item.id && item.name),
        }))
        .filter((group) => group.items.length > 0),
    [groups],
  );
  const hasResults = visibleGroups.length > 0;
  const visibleResults = useMemo<VisibleSearchResult[]>(
    () =>
      visibleGroups.flatMap((group) =>
        group.items.map((item) => ({
          entityType: group.entity_type,
          item,
        })),
      ),
    [visibleGroups],
  );
  const activeResultId =
    focusedResultIndex >= 0 && focusedResultIndex < visibleResults.length
      ? `quick-nav-result-${focusedResultIndex}`
      : undefined;

  const focusSearchInput = useCallback((select = false) => {
    setIsExpanded(true);
    setIsPopoverOpen(true);
    window.setTimeout(() => {
      inputRef.current?.focus();
      if (select) {
        inputRef.current?.select();
      }
    }, 0);
  }, []);

  useEffect(() => {
    setShortcutLabel(getQuickNavShortcutLabel());
  }, []);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
      ) {
        return;
      }

      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        focusSearchInput(true);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [focusSearchInput]);

  useEffect(() => {
    setFocusedResultIndex(-1);
  }, [trimmedQuery, visibleResults.length]);

  useEffect(() => {
    if (trimmedQuery.length < MIN_QUERY_LENGTH) {
      setStatus("idle");
      setGroups([]);
      return;
    }

    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => {
      setStatus("loading");
      searchAdminEntities({
        query: trimmedQuery,
        entityTypes: searchEntityTypes,
        limitPerType: SEARCH_LIMIT_PER_TYPE,
        teamId: selectedTeamId,
        signal: controller.signal,
      })
        .then((payload) => {
          setGroups(Array.isArray(payload.groups) ? payload.groups : []);
          setStatus("success");
        })
        .catch((error) => {
          if (isAbortError(error)) return;
          setGroups([]);
          setStatus("error");
        });
    }, SEARCH_DEBOUNCE_MS);

    return () => {
      window.clearTimeout(timeoutId);
      controller.abort();
    };
  }, [trimmedQuery, searchEntityTypes, selectedTeamId]);

  const buildDestination = useCallback(
    (entityType: SearchEntityType, item: VisibleSearchItem) => {
      const params = new URLSearchParams();
      params.set("selected", item.id);
      params.set("search", trimmedQuery);
      return `${ENTITY_ROUTE[entityType]}?${params.toString()}`;
    },
    [trimmedQuery],
  );

  const handleResultSelect = useCallback(
    (entityType: SearchEntityType, item: VisibleSearchItem) => {
      navigate(buildDestination(entityType, item));
      setIsPopoverOpen(false);
      setIsExpanded(query.length > 0);
    },
    [buildDestination, navigate, query.length],
  );

  const firstResult = visibleGroups[0]?.items[0];
  const firstResultEntity = visibleGroups[0]?.entity_type;

  const handleSearchKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      setIsPopoverOpen(false);
      setFocusedResultIndex(-1);
      return;
    }

    if (visibleResults.length === 0) return;

    if (event.key === "ArrowDown") {
      event.preventDefault();
      setIsPopoverOpen(true);
      setFocusedResultIndex((prev) => Math.min(prev + 1, visibleResults.length - 1));
      return;
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      setIsPopoverOpen(true);
      setFocusedResultIndex((prev) => Math.max(prev - 1, 0));
      return;
    }

    if (event.key === "Enter" && focusedResultIndex >= 0) {
      const focusedResult = visibleResults[focusedResultIndex];
      if (focusedResult) {
        event.preventDefault();
        handleResultSelect(focusedResult.entityType, focusedResult.item);
      }
    }
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (firstResult && firstResultEntity) {
      handleResultSelect(firstResultEntity, firstResult);
    }
  };

  const renderSearchContent = () => {
    if (trimmedQuery.length < MIN_QUERY_LENGTH) {
      return (
        <p className="px-3 py-3 text-sm text-muted-foreground">
          {intl.formatMessage({ id: "common.search.startTyping" }, { count: MIN_QUERY_LENGTH })}
        </p>
      );
    }

    if (status === "loading") {
      return (
        <div className="flex items-center gap-2 px-3 py-3 text-sm text-muted-foreground">
          <Loading variant="inline" />
          <span>{intl.formatMessage({ id: "common.search.searching" })}</span>
        </div>
      );
    }

    if (status === "error") {
      return (
        <p className="px-3 py-3 text-sm text-destructive">
          {intl.formatMessage({ id: "common.search.error" })}
        </p>
      );
    }

    if (status === "success" && !hasResults) {
      return (
        <p className="px-3 py-3 text-sm text-muted-foreground">
          {intl.formatMessage({ id: "common.search.noResults" })}
        </p>
      );
    }

    return visibleGroups.map((group, groupIndex) => (
      <div key={group.entity_type}>
        {groupIndex > 0 ? <Separator /> : null}
        <div className="flex items-center justify-between px-3 py-2">
          <span className="text-xs font-semibold uppercase text-muted-foreground">
            {intl.formatMessage({ id: ENTITY_LABEL_KEY[group.entity_type] })}
          </span>
          <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
            {group.items.length}
          </Badge>
        </div>
        <div className="pb-1">
          {group.items.map((item) => {
            const resultIndex = visibleResults.findIndex(
              (result) => result.entityType === group.entity_type && result.item.id === item.id,
            );
            const isFocused = resultIndex === focusedResultIndex;

            return (
              <Button
                id={`quick-nav-result-${resultIndex}`}
                key={`${group.entity_type}-${item.id}`}
                type="button"
                variant="ghost"
                role="option"
                tabIndex={-1}
                aria-selected={isFocused}
                className={cn(
                  "flex w-full flex-col gap-0.5 px-3 py-2 text-left transition-colors hover:bg-muted focus-visible:bg-muted focus-visible:outline-none",
                  isFocused ? "bg-muted" : "",
                )}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => handleResultSelect(group.entity_type, item)}
              >
                <span className="truncate text-sm font-medium text-foreground">{item.name}</span>
                {item.summary && item.summary !== item.name ? (
                  <span className="truncate text-xs text-muted-foreground">{item.summary}</span>
                ) : null}
              </Button>
            );
          })}
        </div>
      </div>
    ));
  };

  return (
    <div className="hidden md:block">
      <Popover
        open={isPopoverOpen && (isExpanded || query.length > 0)}
        onOpenChange={setIsPopoverOpen}
      >
        <form onSubmit={handleSubmit} className="relative flex items-center gap-2">
          <PopoverTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => focusSearchInput()}
              className="rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              aria-label={intl.formatMessage({ id: "common.search" })}
              title={intl.formatMessage({ id: "common.search" })}
            >
              <Search className="size-4" aria-hidden="true" />
            </Button>
          </PopoverTrigger>
          <PopoverAnchor asChild>
            <Input
              ref={inputRef}
              type="search"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setIsPopoverOpen(true);
              }}
              onKeyDown={handleSearchKeyDown}
              onFocus={() => {
                setIsExpanded(true);
                setIsPopoverOpen(true);
              }}
              onBlur={() => setIsExpanded(query.length > 0)}
              aria-label={intl.formatMessage({ id: "common.search" })}
              aria-controls="quick-nav-results"
              aria-activedescendant={activeResultId}
              aria-expanded={isPopoverOpen && (isExpanded || query.length > 0)}
              data-expanded={isExpanded}
              autoComplete="off"
              placeholder={
                isExpanded || query.length > 0 ? intl.formatMessage({ id: "common.search" }) : ""
              }
              className={cn(
                "h-8 rounded-lg border-border bg-muted/50 pr-2 text-sm shadow-none transition-[width,padding,color,background-color,border-color] duration-200 ease-out placeholder:text-muted-foreground/80 focus-visible:bg-background",
                isExpanded || query.length > 0
                  ? "w-44 px-3 text-foreground md:w-48 lg:w-56"
                  : "w-[3.9rem] px-2 text-transparent caret-foreground",
              )}
            />
          </PopoverAnchor>
          <span
            className={cn(
              "pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 rounded border border-border bg-background px-1.5 py-0.5 text-[10px] font-medium tracking-wide text-muted-foreground transition-opacity duration-150",
              isExpanded || query.length > 0 ? "opacity-0" : "opacity-100",
            )}
          >
            {shortcutLabel}
          </span>
        </form>
        <PopoverContent
          align="start"
          className="w-80 max-w-[calc(100vw-2rem)] p-0"
          onOpenAutoFocus={(event) => event.preventDefault()}
        >
          <div
            id="quick-nav-results"
            role="listbox"
            aria-label={intl.formatMessage({ id: "common.search.results" })}
          >
            {renderSearchContent()}
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
