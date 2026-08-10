import { useCallback, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useIntl } from "react-intl";

import {
  CatalogResults,
  CatalogServerDetailsDialog,
} from "@/components/server-catalog/CatalogResults";
import {
  CatalogToolbar,
  type CatalogSingleFilterKey,
} from "@/components/server-catalog/CatalogToolbar";
import { EmptyStatePlaceholder } from "@/components/dashboard/EmptyStatePlaceholder";
import { InlineNotification } from "@/components/ui/inline-notification";
import { Loading } from "@/components/ui/loading";
import type { CatalogListResponse, CatalogServer } from "@/generated/types";
import { useQuery } from "@/hooks/useQuery";
import { useRouter } from "@/router";

const CATALOG_PATH = "/v1/catalog?limit=1000";
const PAGE_PATH = "/app/server-catalog";
const OPEN_AUTH_TYPE = "Open";
const PAGE_HEADING_ID = "server-catalog-heading";

interface CatalogFilters {
  search: string;
  category: string;
  provider: string;
  authType: string;
  tags: string[];
  installedOnly: boolean;
}

type QueryUpdateValue = string | string[] | boolean | null;

function getQuery(path: string): string {
  const queryIndex = path.indexOf("?");
  return queryIndex === -1 ? "" : path.slice(queryIndex + 1);
}

function parseFilters(path: string): CatalogFilters {
  const params = new URLSearchParams(getQuery(path));

  return {
    search: params.get("search") ?? "",
    category: params.get("category") ?? "",
    provider: params.get("provider") ?? "",
    authType: params.get("auth_type") === OPEN_AUTH_TYPE ? OPEN_AUTH_TYPE : "",
    tags: [...new Set(params.getAll("tags").filter(Boolean))],
    installedOnly: params.get("show_registered_only") === "true",
  };
}

function useCatalogFilters() {
  const { path, navigate } = useRouter();
  const filters = useMemo(() => parseFilters(path), [path]);

  const updateQuery = useCallback(
    (updates: Record<string, QueryUpdateValue>) => {
      const params = new URLSearchParams(getQuery(path));

      Object.entries(updates).forEach(([key, value]) => {
        params.delete(key);
        if (Array.isArray(value)) {
          value.forEach((item) => params.append(key, item));
        } else if (typeof value === "boolean") {
          if (value) params.set(key, "true");
        } else if (value) {
          params.set(key, value);
        }
      });

      const query = params.toString();
      navigate(query ? `${PAGE_PATH}?${query}` : PAGE_PATH);
    },
    [navigate, path],
  );

  const setSingleFilter = useCallback(
    (key: CatalogSingleFilterKey, value: string | null) => updateQuery({ [key]: value }),
    [updateQuery],
  );

  const toggleTag = useCallback(
    (tag: string, checked: boolean) =>
      updateQuery({
        tags: checked ? [...filters.tags, tag] : filters.tags.filter((item) => item !== tag),
      }),
    [filters.tags, updateQuery],
  );

  const clearFilters = useCallback(
    () => updateQuery({ category: null, provider: null, auth_type: null, tags: [] }),
    [updateQuery],
  );

  return { filters, updateQuery, setSingleFilter, toggleTag, clearFilters };
}

function filterOpenServers(servers: CatalogServer[], filters: CatalogFilters): CatalogServer[] {
  const search = filters.search.trim().toLocaleLowerCase();

  return servers.filter((server) => {
    // Catalog MVP is intentionally fail-closed: only the exact Open value is visible.
    if (server.auth_type !== OPEN_AUTH_TYPE) return false;
    if (filters.authType && server.auth_type !== filters.authType) return false;
    if (filters.category && server.category !== filters.category) return false;
    if (filters.provider && server.provider !== filters.provider) return false;
    if (filters.installedOnly && !server.is_registered) return false;
    if (filters.tags.length > 0 && !filters.tags.some((tag) => server.tags?.includes(tag))) {
      return false;
    }

    if (!search) return true;
    return `${server.name} ${server.description}`.toLocaleLowerCase().includes(search);
  });
}

function CatalogPageLayout({ children }: { children: ReactNode }) {
  const intl = useIntl();

  return (
    <section className="p-6" aria-labelledby={PAGE_HEADING_ID}>
      <h1 id={PAGE_HEADING_ID} className="text-base font-semibold text-foreground">
        {intl.formatMessage({ id: "mcpServer.catalog.title" })}
      </h1>
      {children}
    </section>
  );
}

export function ServerCatalog() {
  const intl = useIntl();
  const [selectedServer, setSelectedServer] = useState<CatalogServer | null>(null);
  const lastViewTriggerRef = useRef<HTMLButtonElement | null>(null);
  const { data, error, isLoading } = useQuery<CatalogListResponse>(CATALOG_PATH);
  const { filters, updateQuery, setSingleFilter, toggleTag, clearFilters } = useCatalogFilters();

  const servers = useMemo(
    () => filterOpenServers(data?.servers ?? [], filters),
    [data?.servers, filters],
  );
  const hasOpenServers = Boolean(
    data?.servers.some((server) => server.auth_type === OPEN_AUTH_TYPE),
  );
  const activeFilterCount =
    Number(Boolean(filters.category)) +
    Number(Boolean(filters.provider)) +
    Number(Boolean(filters.authType)) +
    filters.tags.length;

  const handleView = useCallback((server: CatalogServer, trigger: HTMLButtonElement) => {
    lastViewTriggerRef.current = trigger;
    setSelectedServer(server);
  }, []);

  const handleDetailsOpenChange = useCallback((open: boolean) => {
    if (open) return;
    setSelectedServer(null);
    window.setTimeout(() => lastViewTriggerRef.current?.focus(), 0);
  }, []);

  if (isLoading) {
    return (
      <CatalogPageLayout>
        <div aria-busy="true">
          <Loading />
        </div>
      </CatalogPageLayout>
    );
  }

  if (error?.status === 404) {
    return (
      <CatalogPageLayout>
        <div role="status" aria-live="polite" className="mt-6">
          <EmptyStatePlaceholder messageId="mcpServer.catalog.disabled" />
        </div>
      </CatalogPageLayout>
    );
  }

  if (error) {
    return (
      <CatalogPageLayout>
        <div className="mt-6">
          <InlineNotification
            type="error"
            message={intl.formatMessage({ id: "mcpServer.catalog.error" })}
          />
        </div>
      </CatalogPageLayout>
    );
  }

  return (
    <CatalogPageLayout>
      <CatalogToolbar
        search={filters.search}
        installedOnly={filters.installedOnly}
        category={filters.category}
        provider={filters.provider}
        authType={filters.authType}
        selectedTags={filters.tags}
        categories={data?.categories ?? []}
        providers={data?.providers ?? []}
        availableTags={data?.all_tags ?? []}
        activeFilterCount={activeFilterCount}
        onSearchChange={(search) => updateQuery({ search: search || null })}
        onInstalledChange={(installedOnly) => updateQuery({ show_registered_only: installedOnly })}
        onSetSingleFilter={setSingleFilter}
        onToggleTag={toggleTag}
        onClear={clearFilters}
      />

      <CatalogResults servers={servers} hasOpenServers={hasOpenServers} onView={handleView} />

      <CatalogServerDetailsDialog server={selectedServer} onOpenChange={handleDetailsOpenChange} />
    </CatalogPageLayout>
  );
}
