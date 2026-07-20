import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import type { ReactNode } from "react";
import { useIntl } from "react-intl";
import {
  Activity,
  Box,
  Copy,
  EllipsisVertical,
  Loader2,
  MessageSquareCode,
  PanelRightClose,
  Plus,
  Search,
  Users,
  Wrench,
} from "lucide-react";
import { MCPIcon } from "@/components/icons/MCPIcon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { InlineTagAdd } from "@/components/ui/inline-tag-add";
import { CopyValue } from "@/components/ui/copy-value";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { MCPServer, VirtualServer } from "@/types/server";
import type { ComponentFilter } from "@/components/gateways/types";
import { copyToClipboard } from "@/lib/clipboard";
import {
  buildComponentItems,
  formatServerDateTime,
  getTagDisplay,
  getVirtualServerEndpoint,
  truncateMiddle,
} from "@/components/gateways/utils";
import { useQuery } from "@/hooks/useQuery";

const COMPONENT_FILTER_OPTIONS: Array<{ value: ComponentFilter; labelId: string }> = [
  { value: "all", labelId: "gateways.details.filter.all" },
  { value: "tools", labelId: "gateways.details.filter.tools" },
  { value: "resources", labelId: "gateways.details.filter.resources" },
  { value: "prompts", labelId: "gateways.details.filter.prompts" },
];

interface Tool {
  id: string;
  name: string;
  title?: string;
  originalName: string;
  description?: string;
  gatewayId?: string;
  gateway_id?: string;
}

interface Resource {
  id: string;
  name: string;
  title?: string;
  uri: string;
  gatewayId?: string;
  gateway_id?: string;
}

interface Prompt {
  id: string;
  name: string;
  title?: string;
  originalName: string;
  description?: string;
  gatewayId?: string;
  gateway_id?: string;
}

type ComponentWithType =
  (Tool & { type: "tools" }) | (Resource & { type: "resources" }) | (Prompt & { type: "prompts" });

interface MCPServersResponse {
  gateways?: MCPServer[];
  nextCursor?: string | null;
}

type SourceFilter = "all" | string;

function DetailRow({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`grid grid-cols-[96px_minmax(0,1fr)] items-start gap-4 ${className ?? ""}`}>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-foreground">{children}</dd>
    </div>
  );
}

function getComponentIcon(type: Exclude<ComponentFilter, "all">) {
  if (type === "tools") return <Wrench className="size-3.5" />;
  if (type === "resources") return <Box className="size-3.5" />;
  return <MessageSquareCode className="size-3.5" />;
}

function getComponentGatewayId(component: ComponentWithType) {
  return component.gatewayId ?? component.gateway_id;
}

function getComponentIdentifier(component: ComponentWithType) {
  return component.type === "resources" ? component.uri : component.originalName;
}

function getMCPServers(data: MCPServersResponse | MCPServer[] | undefined): MCPServer[] {
  if (Array.isArray(data)) return data;
  return data?.gateways ?? [];
}

export function VirtualServerDetailsPanel({
  server,
  error,
  open,
  onClose,
  onAddSources,
  onAddTag,
}: {
  server: VirtualServer | null;
  error: { message: string } | null;
  open: boolean;
  onClose: () => void;
  onAddSources: () => void;
  /**
   * Persists the server's full tag list after an inline add. Receives the
   * virtual server ID and the new complete list of tag labels. When omitted, the
   * tag row shows a non-interactive "add" affordance.
   */
  onAddTag?: (serverId: string, tags: string[]) => Promise<void>;
}) {
  const intl = useIntl();
  const endpoint = server ? getVirtualServerEndpoint(server.id) : "";
  const tagFallback = intl.formatMessage({ id: "gateways.details.tagFallback" });
  const notSyncedYet = intl.formatMessage({ id: "gateways.card.notSyncedYet" });
  const tags = (server?.tags ?? []).map((tag, index) => getTagDisplay(tag, index, tagFallback));
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [componentFilter, setComponentFilter] = useState<ComponentFilter>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [isSearchExpanded, setIsSearchExpanded] = useState(false);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const headingId = useMemo(() => `server-details-heading-${server?.id ?? "none"}`, [server?.id]);

  const getComponentLabel = useCallback(
    (type: Exclude<ComponentFilter, "all">) =>
      intl.formatMessage({ id: `gateways.details.component.${type}` }),
    [intl],
  );
  const getVisibilityLabel = useCallback(
    (value?: string) => {
      if (value === "team")
        return intl.formatMessage({ id: "gateways.createServer.visibility.team" });
      if (value === "public")
        return intl.formatMessage({ id: "gateways.createServer.visibility.public" });
      if (value === "private")
        return intl.formatMessage({ id: "gateways.createServer.visibility.private" });
      return intl.formatMessage({ id: "gateways.details.notAvailable" });
    },
    [intl],
  );

  const handleTabKeyDown = useCallback(
    (e: KeyboardEvent<HTMLButtonElement>, currentValue: ComponentFilter) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      e.preventDefault();
      const currentIndex = COMPONENT_FILTER_OPTIONS.findIndex((t) => t.value === currentValue);
      const nextIndex =
        e.key === "ArrowRight"
          ? (currentIndex + 1) % COMPONENT_FILTER_OPTIONS.length
          : (currentIndex - 1 + COMPONENT_FILTER_OPTIONS.length) % COMPONENT_FILTER_OPTIONS.length;
      const nextTab = COMPONENT_FILTER_OPTIONS[nextIndex];
      setComponentFilter(nextTab.value);
      document.getElementById(`tab-${nextTab.value}`)?.focus();
    },
    [],
  );

  const handleSourceTabKeyDown = useCallback(
    (e: KeyboardEvent<HTMLButtonElement>, currentIndex: number, sourceCount: number) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      e.preventDefault();
      const nextIndex =
        e.key === "ArrowRight"
          ? (currentIndex + 1) % sourceCount
          : (currentIndex - 1 + sourceCount) % sourceCount;
      document.getElementById(`source-tab-${nextIndex}`)?.focus();
    },
    [],
  );

  // Build API paths - only when server exists
  const toolsPath = useMemo(() => {
    if (!server?.id) return "";
    const params = new URLSearchParams({ include_inactive: "true" });
    return `/servers/${encodeURIComponent(server.id)}/tools?${params}`;
  }, [server?.id]);

  const resourcesPath = useMemo(() => {
    if (!server?.id) return "";
    const params = new URLSearchParams({ include_inactive: "true" });
    return `/servers/${encodeURIComponent(server.id)}/resources?${params}`;
  }, [server?.id]);

  const promptsPath = useMemo(() => {
    if (!server?.id) return "";
    const params = new URLSearchParams({ include_inactive: "true" });
    return `/servers/${encodeURIComponent(server.id)}/prompts?${params}`;
  }, [server?.id]);

  // Fetch components data - only when panel is open and server exists
  const fetchEnabled = open && Boolean(server?.id);
  const { data: toolsData, isLoading: toolsLoading } = useQuery<{ tools: Tool[] }>(toolsPath, {
    enabled: fetchEnabled,
  });

  const { data: resourcesData, isLoading: resourcesLoading } = useQuery<{ resources: Resource[] }>(
    resourcesPath,
    {
      enabled: fetchEnabled,
    },
  );

  const { data: promptsData, isLoading: promptsLoading } = useQuery<{ prompts: Prompt[] }>(
    promptsPath,
    {
      enabled: fetchEnabled,
    },
  );

  const fetchedComponents = useMemo((): ComponentWithType[] => {
    const tools = Array.isArray(toolsData) ? toolsData : toolsData?.tools || [];
    const resources = Array.isArray(resourcesData) ? resourcesData : resourcesData?.resources || [];
    const prompts = Array.isArray(promptsData) ? promptsData : promptsData?.prompts || [];

    return [
      ...tools.map((t): ComponentWithType => ({ ...t, type: "tools" as const })),
      ...resources.map((r): ComponentWithType => ({ ...r, type: "resources" as const })),
      ...prompts.map((p): ComponentWithType => ({ ...p, type: "prompts" as const })),
    ];
  }, [toolsData, resourcesData, promptsData]);

  const fallbackComponents = useMemo((): ComponentWithType[] => {
    if (!server) return [];
    return buildComponentItems(server).map((item): ComponentWithType => {
      if (item.type === "resources") {
        return {
          id: item.id,
          name: item.name,
          title: undefined,
          uri: item.name,
          type: "resources",
        };
      }

      return {
        id: item.id,
        name: item.name,
        title: item.secondary ? item.name : undefined,
        originalName: item.secondary ?? item.name,
        type: item.type,
      };
    });
  }, [server]);

  const allComponents = fetchedComponents.length > 0 ? fetchedComponents : fallbackComponents;

  const sourceIds = useMemo(
    () =>
      Array.from(
        new Set(
          allComponents
            .map((component) => getComponentGatewayId(component))
            .filter((id): id is string => Boolean(id)),
        ),
      ),
    [allComponents],
  );

  const sourcesPath = useMemo(() => {
    const params = new URLSearchParams({ limit: "100", include_inactive: "true" });
    return `/gateways?${params}`;
  }, []);

  const { data: sourcesData, isLoading: sourcesLoading } = useQuery<
    MCPServersResponse | MCPServer[]
  >(sourcesPath, {
    enabled: fetchEnabled && sourceIds.length > 0,
  });

  const sourceTabs = useMemo(() => {
    const serverById = new Map(getMCPServers(sourcesData).map((source) => [source.id, source]));
    return sourceIds.map((id) => {
      const source = serverById.get(id);
      return {
        id,
        label: source?.name ?? truncateMiddle(id, 32),
        source,
      };
    });
  }, [sourceIds, sourcesData]);

  const componentsLoading = toolsLoading || resourcesLoading || promptsLoading;

  // Reset filter and search when the panel opens or the selected server changes.
  useEffect(() => {
    if (!open) return;
    setSourceFilter("all");
    setComponentFilter("all");
    setSearchQuery("");
    setIsSearchExpanded(false);
  }, [open, server?.id]);

  useEffect(() => {
    if (sourceFilter === "all") return;
    if (!sourceIds.includes(sourceFilter)) {
      setSourceFilter("all");
    }
  }, [sourceFilter, sourceIds]);

  // Focus management: focus close button on open, restore focus on close
  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = (document.activeElement as HTMLElement | null) ?? null;
    closeButtonRef.current?.focus();
    return () => {
      previousFocusRef.current?.focus?.();
      previousFocusRef.current = null;
    };
  }, [open]);

  // ESC key handler
  useEffect(() => {
    if (!open) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Filter components based on active tab and search query
  const visibleComponents = useMemo((): ComponentWithType[] => {
    let filtered =
      componentFilter === "all"
        ? allComponents
        : allComponents.filter((c) => c.type === componentFilter);

    if (sourceFilter !== "all") {
      filtered = filtered.filter((component) => getComponentGatewayId(component) === sourceFilter);
    }

    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter((component) => {
        const title = component.title?.toLowerCase() || "";
        const identifier = getComponentIdentifier(component).toLowerCase();
        return title.includes(query) || identifier.includes(query);
      });
    }

    return filtered;
  }, [allComponents, componentFilter, searchQuery, sourceFilter]);

  return (
    <>
      {/* Overlay */}
      <div
        data-state={open ? "open" : "closed"}
        aria-hidden="true"
        onClick={onClose}
        className={cn(
          "absolute inset-0 z-10 bg-black/10 transition-opacity duration-150 supports-backdrop-filter:backdrop-blur-xs",
          "data-[state=open]:opacity-100 data-[state=closed]:opacity-0 data-[state=closed]:pointer-events-none",
        )}
      />

      {/* Panel */}
      <aside
        role="region"
        aria-labelledby={headingId}
        aria-hidden={!open}
        inert={!open ? true : undefined}
        data-state={open ? "open" : "closed"}
        className={cn(
          "absolute inset-y-0 right-0 z-20 flex w-[min(1236px,calc(100%-2rem))] border-l border-border bg-popover text-[13px] shadow-lg",
          "transition-transform duration-200 ease-out",
          "data-[state=open]:translate-x-0 data-[state=closed]:translate-x-full",
          "data-[state=closed]:pointer-events-none",
        )}
      >
        {server && (
          <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[minmax(0,1fr)_320px]">
            <div className="min-w-0 overflow-y-auto px-6 py-8 lg:px-12">
              <h2 id={headingId} className="sr-only">
                {intl.formatMessage({ id: "gateways.details.sheetTitle" }, { name: server.name })}
              </h2>

              <div className="flex items-start justify-between gap-4">
                <div className="flex min-w-0 items-start gap-3">
                  <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-sm bg-primary text-primary-foreground">
                    <MCPIcon className="size-4 [&_path]:fill-current" />
                  </span>
                  <div className="min-w-0">
                    <div className="flex min-w-0 items-center gap-2">
                      <span
                        aria-hidden="true"
                        className="truncate text-xl font-semibold text-foreground"
                      >
                        {server.name}
                      </span>
                    </div>
                  </div>
                </div>

                <Button
                  type="button"
                  variant="default"
                  size="xs"
                  className="h-6 rounded-sm px-2 text-[13px]"
                  onClick={onAddSources}
                >
                  <Plus className="size-3" />
                  {intl.formatMessage({ id: "gateways.details.addSource" })}
                </Button>
              </div>

              <p className="mt-7 max-w-4xl text-[15px] leading-6 text-muted-foreground">
                {server.description || intl.formatMessage({ id: "gateways.details.noDescription" })}
              </p>

              <div className="my-8 h-px bg-border" />

              {(sourcesLoading || sourceTabs.length > 0) && (
                <div
                  role="tablist"
                  aria-label={intl.formatMessage({ id: "gateways.details.filterSources" })}
                  className="flex max-w-full items-center overflow-x-auto rounded-md bg-muted p-1"
                >
                  {[
                    {
                      id: "all",
                      label: intl.formatMessage({ id: "gateways.details.filter.allSources" }),
                    },
                    ...sourceTabs,
                  ].map((source, index, sources) => {
                    const isSelected = sourceFilter === source.id;

                    return (
                      <Button
                        key={source.id}
                        id={`source-tab-${index}`}
                        type="button"
                        variant="ghost"
                        size="sm"
                        role="tab"
                        aria-selected={isSelected}
                        tabIndex={isSelected ? 0 : -1}
                        className={cn(
                          "h-8 shrink-0 rounded-sm px-4 text-sm font-medium transition-colors",
                          isSelected
                            ? "bg-background text-foreground shadow-sm"
                            : "text-muted-foreground hover:text-foreground",
                        )}
                        onClick={() => setSourceFilter(source.id)}
                        onKeyDown={(e) => handleSourceTabKeyDown(e, index, sources.length)}
                      >
                        {source.label}
                      </Button>
                    );
                  })}
                </div>
              )}

              <div className="mt-8 flex items-center justify-between gap-4">
                <div
                  role="tablist"
                  aria-label="Filter components"
                  className="flex min-w-0 items-center gap-6"
                >
                  {COMPONENT_FILTER_OPTIONS.map((option) => (
                    <Button
                      key={option.value}
                      id={`tab-${option.value}`}
                      type="button"
                      variant="ghost"
                      size="sm"
                      role="tab"
                      aria-selected={componentFilter === option.value}
                      tabIndex={componentFilter === option.value ? 0 : -1}
                      className={`text-sm font-semibold transition-colors ${
                        componentFilter === option.value
                          ? "text-foreground"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                      onClick={() => setComponentFilter(option.value)}
                      onKeyDown={(e) => handleTabKeyDown(e, option.value)}
                    >
                      {intl.formatMessage({ id: option.labelId })}
                    </Button>
                  ))}
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    onClick={() => searchInputRef.current?.focus()}
                    className="size-8 rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                    aria-label="Search components"
                  >
                    <Search className="size-4" />
                  </Button>
                  <Input
                    ref={searchInputRef}
                    type="search"
                    tabIndex={isSearchExpanded || searchQuery.length > 0 ? 0 : -1}
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    onFocus={() => setIsSearchExpanded(true)}
                    onBlur={() => setIsSearchExpanded(searchQuery.length > 0)}
                    placeholder={isSearchExpanded || searchQuery.length > 0 ? "Search..." : ""}
                    className={cn(
                      "h-8 rounded-md border-border bg-muted/50 text-sm shadow-none transition-[width,padding,color,background-color,border-color] duration-200 ease-out placeholder:text-muted-foreground focus-visible:bg-background",
                      isSearchExpanded || searchQuery.length > 0
                        ? "w-48 px-3 text-foreground"
                        : "w-0 px-0 text-transparent caret-foreground border-transparent",
                    )}
                  />
                </div>
              </div>

              {error && (
                <div
                  role="alert"
                  className="mt-6 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
                >
                  {error.message}
                </div>
              )}

              <div
                role="tabpanel"
                aria-labelledby={`tab-${componentFilter}`}
                aria-live="polite"
                className="mt-5 divide-y divide-transparent"
              >
                {componentsLoading && (
                  <div role="status" className="flex items-center gap-2 py-8 text-muted-foreground">
                    <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                    <span>Loading components...</span>
                  </div>
                )}

                {!componentsLoading &&
                  visibleComponents.map((component) => {
                    const title = component.title;
                    const identifier = getComponentIdentifier(component);

                    return (
                      <div
                        key={`${component.type}-${component.id}`}
                        className="grid min-h-10 grid-cols-[128px_minmax(0,1fr)_minmax(180px,0.9fr)_24px] items-center gap-4 py-1 text-sm"
                      >
                        <Badge
                          variant="draft"
                          className="w-fit rounded-md px-2 py-0.5 text-[12px] font-medium text-muted-foreground"
                        >
                          <span className="mr-1.5 inline-flex">
                            {getComponentIcon(component.type)}
                          </span>
                          {getComponentLabel(component.type)}
                        </Badge>
                        {title ? (
                          <>
                            <span className="min-w-0 truncate text-muted-foreground">{title}</span>
                            <span className="flex min-w-0 items-center gap-2 font-mono text-[13px] text-muted-foreground">
                              <span className="truncate">{identifier}</span>
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon-xs"
                                aria-label={`Copy ${title}`}
                                className="size-5 text-muted-foreground"
                                onClick={() => copyToClipboard(identifier)}
                              >
                                <Copy className="size-3.5" />
                              </Button>
                            </span>
                          </>
                        ) : (
                          <>
                            <span className="flex min-w-0 items-center gap-2 font-mono text-[13px] text-muted-foreground">
                              <span className="truncate">{identifier}</span>
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon-xs"
                                aria-label={`Copy ${identifier}`}
                                className="size-5 text-muted-foreground"
                                onClick={() => copyToClipboard(identifier)}
                              >
                                <Copy className="size-3.5" />
                              </Button>
                            </span>
                            <span aria-hidden="true" />
                          </>
                        )}
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-xs"
                          aria-label={`Actions for ${title ?? identifier}`}
                          className="justify-self-end text-muted-foreground"
                        >
                          <EllipsisVertical className="size-4" />
                        </Button>
                      </div>
                    );
                  })}

                {!componentsLoading && visibleComponents.length === 0 && (
                  <div className="py-8 text-sm text-muted-foreground">
                    No {componentFilter === "all" ? "components" : componentFilter} found
                  </div>
                )}
              </div>
            </div>

            <aside className="relative border-t border-border bg-background lg:border-l lg:border-t-0">
              <Button
                ref={closeButtonRef}
                type="button"
                variant="ghost"
                size="icon-xs"
                aria-label="Close virtual server details"
                className="absolute right-3 top-3 text-muted-foreground"
                onClick={onClose}
              >
                <PanelRightClose className="size-4" />
              </Button>

              <div className="border-b border-border p-4 pt-8">
                <h3 className="mb-7 text-sm font-semibold text-foreground">
                  {intl.formatMessage({ id: "gateways.details.title" })}
                </h3>

                <dl className="space-y-4">
                  <DetailRow label={intl.formatMessage({ id: "gateways.details.status" })}>
                    <span className="flex items-center gap-2">
                      <Activity className="size-3.5 text-emerald-400" />
                      {server.enabled
                        ? intl.formatMessage({ id: "gateways.details.status.active" })
                        : intl.formatMessage({ id: "gateways.details.status.inactive" })}
                    </span>
                  </DetailRow>
                  <DetailRow label={intl.formatMessage({ id: "gateways.details.visibility" })}>
                    <span className="flex items-center gap-2">
                      <Users className="size-3.5 text-muted-foreground" />
                      {getVisibilityLabel(server.visibility)}
                    </span>
                  </DetailRow>
                  <DetailRow label={intl.formatMessage({ id: "gateways.details.version" })}>
                    {server.version ?? intl.formatMessage({ id: "gateways.details.notAvailable" })}
                  </DetailRow>
                  <DetailRow label={intl.formatMessage({ id: "gateways.details.serverId" })}>
                    <CopyValue label="server ID" value={server.id} />
                  </DetailRow>
                  <DetailRow label={intl.formatMessage({ id: "gateways.details.url" })}>
                    <CopyValue label="URL" value={endpoint} />
                  </DetailRow>
                  {(() => {
                    const tagLabels = tags.map((tag) => tag.label);
                    return (
                      <InlineTagAdd
                        label={intl.formatMessage({ id: "gateways.details.tags" })}
                        existingTags={tagLabels}
                        onAdd={
                          onAddTag && server
                            ? (newTags) => onAddTag(server.id, [...tagLabels, ...newTags])
                            : undefined
                        }
                      >
                        {tags.map((tag) => (
                          <Badge
                            key={tag.key}
                            variant="outline"
                            className="rounded-full px-2 py-0 text-[11px] font-medium text-muted-foreground"
                          >
                            {tag.label}
                          </Badge>
                        ))}
                      </InlineTagAdd>
                    );
                  })()}
                </dl>
              </div>

              <div className="p-4">
                <h3 className="mb-7 text-sm font-semibold text-foreground">
                  {intl.formatMessage({ id: "gateways.details.activity" })}
                </h3>
                <dl className="space-y-4">
                  <DetailRow label={intl.formatMessage({ id: "gateways.details.created" })}>
                    {formatServerDateTime(server.createdAt, notSyncedYet)}
                  </DetailRow>
                  <DetailRow label={intl.formatMessage({ id: "gateways.details.lastModified" })}>
                    {formatServerDateTime(server.updatedAt, notSyncedYet)}
                  </DetailRow>
                </dl>
              </div>
            </aside>
          </div>
        )}
      </aside>
    </>
  );
}
