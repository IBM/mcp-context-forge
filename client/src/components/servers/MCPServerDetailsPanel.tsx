import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import type { ReactNode } from "react";
import {
  Activity,
  Box,
  Copy,
  Globe,
  Loader2,
  MessageSquareCode,
  PanelRightClose,
  Plus,
  Search,
  Server,
  Users,
  Wrench,
} from "lucide-react";
import { MCPIcon } from "@/components/icons/MCPIcon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { MCPServer as BaseMCPServer, VirtualServerTag } from "@/types/server";
import { copyToClipboard } from "@/lib/clipboard";
import { truncateMiddle } from "@/components/gateways/utils";
import { useQuery } from "@/hooks/useQuery";

interface MCPServer extends BaseMCPServer {
  tags?: Array<string | VirtualServerTag>;
}

type ComponentTab = "all" | "tools" | "resources" | "prompts";

const TABS: Array<{ value: ComponentTab; label: string }> = [
  { value: "all", label: "All" },
  { value: "tools", label: "Tools" },
  { value: "resources", label: "Resources" },
  { value: "prompts", label: "Prompts" },
];

interface Tool {
  id: string;
  name: string;
  title?: string;
  originalName: string;
  description?: string;
}

interface Resource {
  id: string;
  name: string;
  title?: string;
  uri: string;
}

interface Prompt {
  id: string;
  name: string;
  title?: string;
  originalName: string;
  description?: string;
}

type ComponentWithType =
  | (Tool & { type: "tools" })
  | (Resource & { type: "resources" })
  | (Prompt & { type: "prompts" });

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

function CopyValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-w-0 items-center gap-2">
      <span className="min-w-0 flex-1 truncate font-mono text-[12px]">{truncateMiddle(value)}</span>
      <Button
        type="button"
        variant="ghost"
        size="icon-xs"
        className="size-5 text-muted-foreground"
        aria-label={`Copy ${label}`}
        onClick={() => copyToClipboard(value)}
      >
        <Copy className="size-3.5" />
      </Button>
    </div>
  );
}

function formatDateTime(value?: string, emptyLabel = "Not available") {
  if (!value) return emptyLabel;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

function formatLastSeen(lastSeen?: string): string {
  if (!lastSeen) return "Never used";

  const date = new Date(lastSeen);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);

  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins} min ago`;

  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours} hour${diffHours > 1 ? "s" : ""} ago`;

  return date.toLocaleDateString("en-US", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function getComponentIcon(type: Exclude<ComponentTab, "all">) {
  if (type === "tools") return <Wrench className="size-3.5" aria-hidden="true" />;
  if (type === "resources") return <Box className="size-3.5" aria-hidden="true" />;
  return <MessageSquareCode className="size-3.5" aria-hidden="true" />;
}

export function MCPServerDetailsPanel({
  server,
  error,
  open,
  onClose,
}: {
  server: MCPServer | null;
  error: { message: string } | null;
  open: boolean;
  onClose: () => void;
}) {
  const [activeTab, setActiveTab] = useState<ComponentTab>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [isSearchExpanded, setIsSearchExpanded] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const headingId = useMemo(() => `server-details-heading-${server?.id ?? "none"}`, [server?.id]);

  // Reset tab and search when server changes
  useEffect(() => {
    setActiveTab("all");
    setSearchQuery("");
    setIsSearchExpanded(false);
  }, [server?.id]);

  // Focus close on open; restore focus on close/unmount.
  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = (document.activeElement as HTMLElement | null) ?? null;
    closeButtonRef.current?.focus();
    return () => {
      previousFocusRef.current?.focus?.();
      previousFocusRef.current = null;
    };
  }, [open]);

  // ESC closes while open.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Build API paths - only when server exists
  const toolsPath = useMemo(() => {
    if (!server?.id) return "/tools";
    const params = new URLSearchParams({ gateway_id: server.id, include_inactive: "true" });
    return `/tools?${params}`;
  }, [server?.id]);

  const resourcesPath = useMemo(() => {
    if (!server?.id) return "/resources";
    const params = new URLSearchParams({ gateway_id: server.id, include_inactive: "true" });
    return `/resources?${params}`;
  }, [server?.id]);

  const promptsPath = useMemo(() => {
    if (!server?.id) return "/prompts";
    const params = new URLSearchParams({ gateway_id: server.id, include_inactive: "true" });
    return `/prompts?${params}`;
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

  const componentsLoading = toolsLoading || resourcesLoading || promptsLoading;

  // Filter components based on active tab and search query
  const visibleComponents = useMemo((): ComponentWithType[] => {
    const tools = Array.isArray(toolsData) ? toolsData : toolsData?.tools || [];
    const resources = Array.isArray(resourcesData) ? resourcesData : resourcesData?.resources || [];
    const prompts = Array.isArray(promptsData) ? promptsData : promptsData?.prompts || [];

    const allComponents: ComponentWithType[] = [
      ...tools.map((t): ComponentWithType => ({ ...t, type: "tools" as const })),
      ...resources.map((r): ComponentWithType => ({ ...r, type: "resources" as const })),
      ...prompts.map((p): ComponentWithType => ({ ...p, type: "prompts" as const })),
    ];

    let filtered =
      activeTab === "all" ? allComponents : allComponents.filter((c) => c.type === activeTab);

    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter((component) => {
        const title = component.title?.toLowerCase() || "";
        const identifier =
          component.type === "resources"
            ? component.uri.toLowerCase()
            : component.originalName.toLowerCase();
        return title.includes(query) || identifier.includes(query);
      });
    }

    return filtered;
  }, [toolsData, resourcesData, promptsData, activeTab, searchQuery]);

  const getVisibilityLabel = useCallback((value?: string) => {
    if (value === "team") return "Team";
    if (value === "public") return "Public";
    if (value === "private") return "Private";
    return "Not available";
  }, []);

  const getTransportLabel = useCallback((transport?: string) => {
    if (transport === "SSE") return "Server-Sent Events (SSE)";
    if (transport === "STREAMABLEHTTP") return "Streamable HTTP";
    return transport ?? "Not available";
  }, []);

  const handleTabKeyDown = useCallback(
    (e: KeyboardEvent<HTMLButtonElement>, currentValue: ComponentTab) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      e.preventDefault();
      const currentIndex = TABS.findIndex((t) => t.value === currentValue);
      const nextIndex =
        e.key === "ArrowRight"
          ? (currentIndex + 1) % TABS.length
          : (currentIndex - 1 + TABS.length) % TABS.length;
      const nextTab = TABS[nextIndex];
      setActiveTab(nextTab.value);
      document.getElementById(`tab-${nextTab.value}`)?.focus();
    },
    [],
  );

  return (
    <>
      <div
        data-state={open ? "open" : "closed"}
        aria-hidden="true"
        onClick={onClose}
        className={cn(
          "absolute inset-0 z-10 bg-black/10 transition-opacity duration-150 supports-backdrop-filter:backdrop-blur-xs",
          "data-[state=open]:opacity-100 data-[state=closed]:opacity-0 data-[state=closed]:pointer-events-none",
        )}
      />

      <aside
        role="region"
        aria-labelledby={headingId}
        aria-hidden={!open}
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
                MCP Server details: {server.name}
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
              </div>

              <p className="mt-7 max-w-4xl text-[15px] leading-6 text-muted-foreground">
                {server.description || "No description provided"}
              </p>

              <div className="my-8 h-px bg-border" />

              <div className="flex items-center justify-between gap-4">
                <h3 className="text-sm font-semibold text-foreground">Components</h3>
              </div>

              <div className="mt-8 flex min-w-0 items-center justify-between gap-6">
                <div
                  role="tablist"
                  aria-label="Filter components"
                  className="flex min-w-0 items-center gap-6"
                >
                  {TABS.map((tab) => (
                    <button
                      key={tab.value}
                      id={`tab-${tab.value}`}
                      type="button"
                      role="tab"
                      aria-selected={activeTab === tab.value}
                      tabIndex={activeTab === tab.value ? 0 : -1}
                      className={`text-sm font-semibold transition-colors ${
                        activeTab === tab.value
                          ? "text-foreground"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                      onClick={() => setActiveTab(tab.value)}
                      onKeyDown={(e) => handleTabKeyDown(e, tab.value)}
                    >
                      {tab.label}
                    </button>
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
                    aria-label="Search components"
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
                aria-labelledby={`tab-${activeTab}`}
                className="mt-5 divide-y divide-transparent"
              >
                {componentsLoading && (
                  <div
                    role="status"
                    aria-live="polite"
                    className="flex items-center gap-2 py-8 text-muted-foreground"
                  >
                    <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                    <span>Loading components...</span>
                  </div>
                )}

                {!componentsLoading && visibleComponents.length === 0 && (
                  <div className="py-8 text-sm text-muted-foreground">
                    No {activeTab === "all" ? "components" : activeTab} found
                  </div>
                )}

                {!componentsLoading &&
                  visibleComponents.map((component) => {
                    const title = component.title;
                    const identifier =
                      component.type === "resources" ? component.uri : component.originalName;

                    return (
                      <div
                        key={`${component.type}-${component.id}`}
                        className="grid min-h-10 grid-cols-[128px_minmax(0,1fr)_minmax(180px,0.9fr)] items-center gap-4 py-1 text-sm"
                      >
                        <Badge
                          variant="draft"
                          className="w-fit rounded-md px-2 py-0.5 text-[12px] font-medium text-muted-foreground"
                        >
                          <span className="mr-1.5 inline-flex">
                            {getComponentIcon(component.type)}
                          </span>
                          {component.type.slice(0, -1)}
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
                      </div>
                    );
                  })}
              </div>
            </div>

            <aside className="relative border-t border-border bg-background lg:border-l lg:border-t-0">
              <Button
                ref={closeButtonRef}
                type="button"
                variant="ghost"
                size="icon-xs"
                aria-label="Close MCP server details"
                className="absolute right-3 top-3 text-muted-foreground"
                onClick={onClose}
              >
                <PanelRightClose className="size-4" />
              </Button>

              <div className="border-b border-border p-4 pt-8">
                <h3 className="mb-7 text-sm font-semibold text-foreground">Details</h3>

                <dl className="space-y-4">
                  <DetailRow label="Status">
                    <span className="flex items-center gap-2">
                      <Activity
                        className={`size-3.5 ${
                          server.enabled && server.reachable ? "text-emerald-400" : "text-gray-400"
                        }`}
                      />
                      {server.enabled ? (server.reachable ? "Active" : "Unreachable") : "Inactive"}
                    </span>
                  </DetailRow>
                  <DetailRow label="Visibility">
                    <span className="flex items-center gap-2">
                      <Users className="size-3.5 text-muted-foreground" />
                      {getVisibilityLabel(server.visibility)}
                    </span>
                  </DetailRow>
                  <DetailRow label="Transport">
                    <span className="flex items-center gap-2">
                      <Server className="size-3.5 text-muted-foreground" />
                      {getTransportLabel(server.transport)}
                    </span>
                  </DetailRow>
                  <DetailRow label="UUID">
                    <CopyValue label="UUID" value={server.id} />
                  </DetailRow>
                  <DetailRow label="URL">
                    <span className="flex items-center gap-2">
                      <Globe className="size-3.5 text-muted-foreground" />
                      <CopyValue label="URL" value={server.url} />
                    </span>
                  </DetailRow>
                  {server.team && (
                    <DetailRow label="Team">
                      <span className="text-foreground">{server.team}</span>
                    </DetailRow>
                  )}
                  <DetailRow label="Tags" className="items-center">
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                      {(server.tags || []).length > 0 ? (
                        <>
                          {(server.tags || []).map((tag, index) => {
                            const tagLabel =
                              typeof tag === "string"
                                ? tag
                                : tag.label || tag.name || tag.value || tag.id || "Tag";
                            const tagKey = typeof tag === "string" ? tag : tag.id || tagLabel;
                            return (
                              <Badge
                                key={`${tagKey}-${index}`}
                                variant="outline"
                                className="rounded-full px-2 py-0 text-[11px] font-medium text-muted-foreground"
                              >
                                {tagLabel}
                              </Badge>
                            );
                          })}
                          <button
                            type="button"
                            tabIndex={-1}
                            aria-hidden="true"
                            className="flex items-center gap-1 text-[12px] text-muted-foreground hover:text-foreground"
                          >
                            <Plus className="size-3" aria-hidden="true" />
                            add
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          tabIndex={-1}
                          aria-hidden="true"
                          className="flex items-center gap-1 text-[12px] text-muted-foreground hover:text-foreground"
                        >
                          <Plus className="size-3" aria-hidden="true" />
                          add
                        </button>
                      )}
                    </div>
                  </DetailRow>
                  {server.owner_email && (
                    <DetailRow label="Owner">
                      <span className="text-foreground">{server.owner_email}</span>
                    </DetailRow>
                  )}
                </dl>
              </div>

              <div className="p-4">
                <h3 className="mb-7 text-sm font-semibold text-foreground">Activity</h3>
                <dl className="space-y-4">
                  <DetailRow label="Created">{formatDateTime(server.createdAt)}</DetailRow>
                  <DetailRow label="Last modified">{formatDateTime(server.updatedAt)}</DetailRow>
                  <DetailRow label="Last seen">{formatLastSeen(server.lastSeen)}</DetailRow>
                </dl>
              </div>
            </aside>
          </div>
        )}
      </aside>
    </>
  );
}
