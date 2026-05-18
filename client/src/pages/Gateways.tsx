import { useMemo, useState } from "react";
import { useRouter } from "@/router";
import { MainNavIcon } from "@/components/icons/MainNavIcon";
import { MCPIcon } from "@/components/icons/MCPIcon";
import { PromptIcon } from "@/components/icons/PromptIcon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Activity,
  Blocks,
  Bot,
  Box,
  Code,
  Copy,
  EllipsisVertical,
  Filter,
  PanelRightClose,
  Plus,
  Search,
  Upload,
  Users,
  Wrench,
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useQuery } from "@/hooks/useQuery";
import type { VirtualServer, VirtualServerTag, VirtualServersResponse } from "@/types/server";
import { Loading } from "@/components/ui/loading";

const DEFAULT_PAGE_SIZE = 12;
const SERVERS_QUERY_PATH = `/servers?limit=${DEFAULT_PAGE_SIZE}&include_pagination=true`;

interface ActionCard {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
  buttonText: string;
  onAction: () => void;
  disabled?: boolean;
  disabledReason?: string;
}

type ComponentFilter = "all" | "tools" | "resources" | "prompts";

interface DetailComponentItem {
  id: string;
  name: string;
  secondary?: string;
  type: Exclude<ComponentFilter, "all">;
}

function formatServerTimestamp(value?: string) {
  if (!value) return "Not synced yet";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

function formatServerDateTime(value?: string) {
  if (!value) return "N/A";
  return value.replace(/Z$/, "");
}

function formatVisibility(value?: string) {
  if (!value) return "N/A";
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function truncateMiddle(value: string, maxLength = 24) {
  if (value.length <= maxLength) return value;
  const edgeLength = Math.max(4, Math.floor((maxLength - 3) / 2));
  return `${value.slice(0, edgeLength)}...${value.slice(-edgeLength)}`;
}

function getVirtualServerEndpoint(serverId: string) {
  if (typeof window === "undefined" || !window.location?.origin) {
    return `/servers/${serverId}/mcp`;
  }
  return `${window.location.origin}/servers/${serverId}/mcp`;
}

function copyToClipboard(value: string) {
  void navigator.clipboard?.writeText(value);
}

function getTagDisplay(tag: string | VirtualServerTag, index: number) {
  if (typeof tag === "string") {
    return { key: `${tag}-${index}`, label: tag };
  }

  const label = tag.label ?? tag.name ?? tag.value ?? tag.id ?? "Tag";
  return { key: `${tag.id ?? label}-${index}`, label };
}

function getComponentIcon(type: DetailComponentItem["type"]) {
  if (type === "tools") return <Wrench className="size-3.5" />;
  if (type === "resources") return <Box className="size-3.5" />;
  return <PromptIcon className="size-3.5" />;
}

function getComponentLabel(type: DetailComponentItem["type"]) {
  if (type === "tools") return "tool";
  if (type === "resources") return "resource";
  return "prompt";
}

function buildComponentItems(server: VirtualServer): DetailComponentItem[] {
  const toolNames = server.associatedTools ?? [];
  const toolIds = server.associatedToolIds ?? [];
  const toolItems = (toolIds.length > 0 ? toolIds : toolNames).map((idOrName, index) => {
    const name = toolNames[index] ?? idOrName;
    const secondary = toolIds[index] && toolIds[index] !== name ? toolIds[index] : undefined;
    return {
      id: `tool-${idOrName}-${index}`,
      name,
      secondary,
      type: "tools" as const,
    };
  });

  const resourceItems = (server.associatedResources ?? []).map((resource, index) => ({
    id: `resource-${resource}-${index}`,
    name: resource,
    type: "resources" as const,
  }));

  const promptItems = (server.associatedPrompts ?? []).map((prompt, index) => ({
    id: `prompt-${prompt}-${index}`,
    name: prompt,
    type: "prompts" as const,
  }));

  return [...toolItems, ...resourceItems, ...promptItems];
}

function ConnectSourceCard({ onAction }: { onAction: () => void }) {
  return (
    <Card
      size="sm"
      role="button"
      tabIndex={0}
      className="min-h-35 cursor-pointer justify-center transition-colors hover:bg-muted/40"
      onClick={onAction}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onAction();
        }
      }}
    >
      <CardHeader className="gap-3">
        <div className="flex items-center gap-3">
          <span className="flex size-6 items-center justify-center rounded-sm bg-primary text-primary-foreground">
            <Plus className="size-4" />
          </span>
          <CardTitle>Connect a source</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <CardDescription className="text-[13px] leading-4">
          Make an external source available through a virtual server endpoint. Sources can be
          running MCP servers, REST APIs, gRPC services, or A2A agents
        </CardDescription>
      </CardContent>
    </Card>
  );
}

function DetailRow({
  label,
  children,
  className,
}: {
  label: string;
  children: React.ReactNode;
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

function VirtualServerDetailsDrawer({
  server,
  isLoading,
  error,
  onAddComponents,
  onAddSources,
  onOpenChange,
}: {
  server: VirtualServer | null;
  isLoading: boolean;
  error: { message: string } | null;
  onAddComponents: () => void;
  onAddSources: () => void;
  onOpenChange: (open: boolean) => void;
}) {
  const endpoint = server ? getVirtualServerEndpoint(server.id) : "";
  const tags = (server?.tags ?? []).map(getTagDisplay);
  const [componentFilter, setComponentFilter] = useState<ComponentFilter>("all");
  const componentItems = server ? buildComponentItems(server) : [];
  const visibleComponentItems =
    componentFilter === "all"
      ? componentItems
      : componentItems.filter((item) => item.type === componentFilter);
  const filterOptions: Array<{ value: ComponentFilter; label: string }> = [
    { value: "all", label: "All" },
    { value: "tools", label: "Tools" },
    { value: "resources", label: "Resources" },
    { value: "prompts", label: "Prompts" },
  ];

  return (
    <Sheet open={Boolean(server)} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        showCloseButton={false}
        className="data-[side=right]:!w-[min(1236px,calc(100vw-2rem))] data-[side=right]:!max-w-none data-[side=right]:sm:!max-w-none gap-0 overflow-hidden border-l border-border bg-background p-0 text-[13px]"
      >
        {server && (
          <>
            <SheetHeader className="sr-only">
              <SheetTitle>{server.name} details</SheetTitle>
              <SheetDescription>Virtual server details and activity.</SheetDescription>
            </SheetHeader>

            <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[minmax(0,1fr)_320px]">
              <div className="min-w-0 overflow-y-auto px-6 py-8 lg:px-12">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex min-w-0 items-start gap-3">
                    <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-sm bg-primary text-primary-foreground">
                      <MCPIcon className="size-4 [&_path]:fill-current" />
                    </span>
                    <div className="min-w-0">
                      <div className="flex min-w-0 items-center gap-2">
                        <h2 className="truncate text-xl font-semibold text-foreground">
                          {server.name}
                        </h2>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-xs"
                          aria-label={`${server.name} detail actions`}
                          className="text-muted-foreground"
                        >
                          <EllipsisVertical className="size-4" />
                        </Button>
                      </div>
                    </div>
                  </div>

                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 gap-1.5 bg-background"
                    onClick={onAddSources}
                  >
                    <Plus className="size-3.5" />
                    Add sources
                  </Button>
                </div>

                <p className="mt-7 max-w-4xl text-[15px] leading-6 text-muted-foreground">
                  {server.description || "No description provided."}
                </p>

                <div className="my-8 h-px bg-border" />

                <div className="flex items-center justify-between gap-4">
                  <h3 className="text-sm font-semibold text-foreground">Components</h3>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 gap-1.5 bg-background"
                    onClick={onAddComponents}
                  >
                    <Plus className="size-3.5" />
                    Add components
                  </Button>
                </div>

                <div className="mt-8 flex items-center justify-between gap-4">
                  <div className="flex min-w-0 items-center gap-6">
                    {filterOptions.map((option) => (
                      <button
                        key={option.value}
                        type="button"
                        className={`text-sm font-semibold transition-colors ${
                          componentFilter === option.value
                            ? "text-foreground"
                            : "text-muted-foreground hover:text-foreground"
                        }`}
                        onClick={() => setComponentFilter(option.value)}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                  <div className="flex shrink-0 items-center gap-2 text-muted-foreground">
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      aria-label="Search components"
                    >
                      <Search className="size-4" />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      aria-label="Filter components"
                    >
                      <Filter className="size-4" />
                    </Button>
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

                <div className="mt-5 divide-y divide-transparent">
                  {isLoading && (
                    <div className="flex items-center gap-2 py-8 text-muted-foreground">
                      <Loading />
                      <span>Loading server details...</span>
                    </div>
                  )}

                  {!isLoading &&
                    visibleComponentItems.map((item) => (
                      <div
                        key={item.id}
                        className="grid min-h-10 grid-cols-[128px_minmax(0,1fr)_minmax(180px,0.9fr)_24px] items-center gap-4 py-1 text-sm"
                      >
                        <Badge
                          variant="draft"
                          className="w-fit rounded-md px-2 py-0.5 text-[12px] font-medium text-muted-foreground"
                        >
                          <span className="mr-1.5 inline-flex">{getComponentIcon(item.type)}</span>
                          {getComponentLabel(item.type)}
                        </Badge>
                        <span className="min-w-0 truncate text-muted-foreground">{item.name}</span>
                        <span className="flex min-w-0 items-center gap-2 font-mono text-[13px] text-muted-foreground">
                          <span className="truncate">{item.secondary ?? item.name}</span>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-xs"
                            aria-label={`Copy ${item.name}`}
                            className="size-5 text-muted-foreground"
                            onClick={() => copyToClipboard(item.secondary ?? item.name)}
                          >
                            <Copy className="size-3.5" />
                          </Button>
                        </span>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-xs"
                          aria-label={`Actions for ${item.name}`}
                          className="text-muted-foreground"
                        >
                          <EllipsisVertical className="size-4" />
                        </Button>
                      </div>
                    ))}

                  {!isLoading && visibleComponentItems.length === 0 && (
                    <div className="py-8 text-sm text-muted-foreground">
                      No {componentFilter === "all" ? "components" : componentFilter} found.
                    </div>
                  )}
                </div>
              </div>

              <aside className="relative border-t border-border bg-background lg:border-l lg:border-t-0">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  aria-label="Close virtual server details"
                  className="absolute right-3 top-3 text-muted-foreground"
                  onClick={() => onOpenChange(false)}
                >
                  <PanelRightClose className="size-4" />
                </Button>

                <div className="border-b border-border p-4 pt-8">
                  <h3 className="mb-7 text-sm font-semibold text-foreground">
                    Virtual server details
                  </h3>

                  <dl className="space-y-4">
                    <DetailRow label="Status">
                      <span className="flex items-center gap-2">
                        <Activity className="size-3.5 text-emerald-400" />
                        {server.enabled ? "Active" : "Inactive"}
                      </span>
                    </DetailRow>
                    <DetailRow label="Visibility">
                      <span className="flex items-center gap-2">
                        <Users className="size-3.5 text-muted-foreground" />
                        {formatVisibility(server.visibility)}
                      </span>
                    </DetailRow>
                    <DetailRow label="Version">{server.version ?? "N/A"}</DetailRow>
                    <DetailRow label="Server ID">
                      <CopyValue label="server ID" value={server.id} />
                    </DetailRow>
                    <DetailRow label="URL">
                      <CopyValue label="URL" value={endpoint} />
                    </DetailRow>
                    <DetailRow label="Tags" className="items-center">
                      <div className="flex min-w-0 flex-wrap items-center gap-2">
                        {tags.map((tag) => (
                          <Badge
                            key={tag.key}
                            variant="outline"
                            className="rounded-full px-2 py-0 text-[11px] font-medium text-muted-foreground"
                          >
                            {tag.label}
                          </Badge>
                        ))}
                        <button
                          type="button"
                          className="text-[12px] text-muted-foreground hover:text-foreground"
                        >
                          + add
                        </button>
                      </div>
                    </DetailRow>
                  </dl>
                </div>

                <div className="p-4">
                  <h3 className="mb-7 text-sm font-semibold text-foreground">Activity</h3>
                  <dl className="space-y-4">
                    <DetailRow label="Created">{formatServerDateTime(server.createdAt)}</DetailRow>
                    <DetailRow label="Last modified">
                      {formatServerDateTime(server.updatedAt)}
                    </DetailRow>
                  </dl>
                </div>
              </aside>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

function VirtualServerCard({
  server,
  onViewDetails,
}: {
  server: VirtualServer;
  onViewDetails: (server: VirtualServer) => void;
}) {
  const toolCount = server.associatedToolIds?.length ?? 0;
  const resourceCount = server.associatedResources?.length ?? 0;
  const promptCount = server.associatedPrompts?.length ?? 0;
  const tags = (server.tags ?? []).map(getTagDisplay);

  return (
    <Card
      size="sm"
      className="min-h-35 justify-between"
      data-testid="virtual-server-card"
      data-server-name={server.name}
    >
      <CardHeader className="gap-3">
        <div className="flex items-center gap-3">
          <span className="flex size-6 shrink-0 items-center justify-center rounded-sm bg-primary text-primary-foreground">
            <MCPIcon className="size-4 [&_path]:fill-current" />
          </span>
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <CardTitle className="truncate">{server.name}</CardTitle>
            {server.enabled && (
              <span
                className="size-1.5 rounded-full bg-emerald-500"
                data-testid="enabled-indicator"
                aria-label="Enabled"
              />
            )}
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label={`Open ${server.name} (coming soon)`}
              disabled
            >
              <Upload className="size-4" />
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon-xs" aria-label={`Actions for ${server.name}`}>
                  <EllipsisVertical className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => onViewDetails(server)}>
                  View details
                </DropdownMenuItem>
                <DropdownMenuItem disabled>Test connection</DropdownMenuItem>
                <DropdownMenuItem disabled>Edit server</DropdownMenuItem>
                <DropdownMenuItem disabled className="text-destructive">
                  Delete
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center gap-3 text-[13px] font-medium text-secondary-foreground">
          <span className="flex items-center gap-2" data-testid="tool-count">
            <Wrench className="size-4 text-muted-foreground" />
            {toolCount}
          </span>
          <span className="text-border">•</span>
          <span className="flex items-center gap-2" data-testid="resource-count">
            <Box className="size-4 text-muted-foreground" />
            {resourceCount}
          </span>
          <span className="text-border">•</span>
          <span className="flex items-center gap-2" data-testid="prompt-count">
            <PromptIcon className="size-4 text-muted-foreground" />
            {promptCount}
          </span>
        </div>
        <div className="flex items-center gap-2 overflow-hidden">
          <div className="flex min-w-0 flex-1 items-center gap-2 overflow-hidden">
            {tags.map((tag) => (
              <Badge
                key={tag.key}
                variant="outline"
                className="shrink-0 px-1.5 py-0 text-[10px] font-medium text-muted-foreground"
              >
                {tag.label}
              </Badge>
            ))}
          </div>
          <span
            className="shrink-0 truncate text-[13px] text-muted-foreground"
            data-testid="last-updated"
          >
            {formatServerTimestamp(server.updatedAt || server.createdAt)}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

function SourceSelection({ actionCards }: { actionCards: ActionCard[] }) {
  const firstEnabledIndex = actionCards.findIndex((card) => !card.disabled);
  const initialSelectedIndex = firstEnabledIndex === -1 ? 0 : firstEnabledIndex;
  const [selectedIndex, setSelectedIndex] = useState(initialSelectedIndex);

  return (
    <div className="flex min-h-[calc(100vh-12rem)] items-center justify-center">
      <div className="w-full max-w-5xl space-y-12 px-6">
        <div className="flex items-center justify-center gap-3">
          <MainNavIcon className="h-10 w-10 text-neutral-900 dark:text-neutral-50" />
          <h1 className="text-3xl font-semibold text-neutral-900 dark:text-neutral-50">
            Connect a source
          </h1>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {actionCards.map((card, index) => {
            const IconComponent = card.icon;
            const isDisabled = Boolean(card.disabled);
            const isSelected = index === selectedIndex && !isDisabled;
            const cardClasses = isDisabled
              ? "group/action-card flex cursor-not-allowed flex-col opacity-60"
              : `group/action-card flex cursor-pointer flex-col transition-all hover:border-[#FF832B] hover:shadow-md hover:ring-[#FF832B] ${
                  isSelected ? "border-[#FF832B] shadow-md ring-1 ring-[#FF832B]" : ""
                }`;
            return (
              <Card
                key={card.title}
                aria-disabled={isDisabled || undefined}
                data-testid={`action-card-${card.title}`}
                className={cardClasses}
                onClick={() => {
                  if (!isDisabled) setSelectedIndex(index);
                }}
              >
                <CardHeader>
                  <CardTitle
                    className={`flex items-center gap-2 transition-colors group-hover/action-card:text-neutral-900 dark:group-hover/action-card:text-white ${
                      isSelected ? "text-neutral-900 dark:text-white" : "text-muted-foreground"
                    }`}
                  >
                    <IconComponent
                      className={`h-5 w-5 transition-colors group-hover/action-card:text-neutral-900 dark:group-hover/action-card:text-white ${
                        isSelected ? "text-neutral-900 dark:text-white" : "text-muted-foreground"
                      }`}
                    />
                    {card.title}
                  </CardTitle>
                </CardHeader>
                <CardContent className="flex-grow">
                  <CardDescription
                    className={`transition-colors group-hover/action-card:text-neutral-900 dark:group-hover/action-card:text-white ${
                      isSelected ? "text-neutral-900 dark:text-white" : ""
                    }`}
                  >
                    {card.description}
                    {isDisabled && card.disabledReason && (
                      <span className="mt-1 block text-xs italic">{card.disabledReason}</span>
                    )}
                  </CardDescription>
                </CardContent>
                <CardFooter className="mt-auto">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={isDisabled}
                    onClick={(event) => {
                      event.stopPropagation();
                      if (!isDisabled) card.onAction();
                    }}
                    aria-label={
                      isDisabled ? `${card.buttonText} ${card.title} (coming soon)` : undefined
                    }
                    className="w-full bg-neutral-900 text-white hover:bg-neutral-800 hover:text-white dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-100 dark:hover:text-neutral-900"
                  >
                    {card.buttonText}
                  </Button>
                </CardFooter>
              </Card>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export function Gateways() {
  const { navigate } = useRouter();
  const { data, error, isLoading } = useQuery<VirtualServersResponse>(SERVERS_QUERY_PATH);
  const [detailsServer, setDetailsServer] = useState<VirtualServer | null>(null);
  const {
    data: serverDetails,
    error: serverDetailsError,
    isLoading: isServerDetailsLoading,
  } = useQuery<VirtualServer>(`/servers/${detailsServer?.id ?? "__pending__"}`, {
    enabled: Boolean(detailsServer),
  });
  const servers = data?.servers ?? [];
  const hydratedDetailsServer =
    detailsServer && serverDetails?.id === detailsServer.id ? serverDetails : detailsServer;

  const actionCards: ActionCard[] = useMemo(
    () => [
      {
        icon: MCPIcon,
        title: "MCP server",
        description: "Register an endpoint implementing the Model Context Protocol",
        buttonText: "+ Connect",
        onAction: () => navigate("/app/servers?openForm=true"),
      },
      {
        icon: Bot,
        title: "AI agent",
        description: "Add an agent over A2A, OpenAI, or Anthropic protocols",
        buttonText: "+ Connect",
        onAction: () => navigate("/app/agents"),
      },
      {
        icon: Code,
        title: "REST API",
        description: "Wrap a HTTP endpoint as a MCP tool",
        buttonText: "+ Connect",
        disabled: true,
        disabledReason: "Coming soon",
        onAction: () => undefined,
      },
      {
        icon: Blocks,
        title: "gRPC",
        description: "Translate a gRPC endpoint as a MCP tool.",
        buttonText: "+ Connect",
        disabled: true,
        disabledReason: "Coming soon",
        onAction: () => undefined,
      },
    ],
    [navigate],
  );

  if (isLoading) {
    return (
      <div className="p-6">
        <div
          role="status"
          aria-live="polite"
          aria-busy="true"
          className="flex items-center justify-center p-12"
        >
          <Loading />
          <span className="sr-only">Loading virtual servers, please wait...</span>
        </div>
      </div>
    );
  }

  if (error && servers.length === 0) {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4" role="alert">
          <h1 className="font-semibold text-destructive">Error loading virtual servers</h1>
          <p className="text-sm text-destructive">{error.message}</p>
        </div>
      </div>
    );
  }

  if (servers.length > 0) {
    return (
      <div className="space-y-9 p-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h1 className="text-base font-semibold text-foreground">Virtual servers</h1>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon-xs" aria-label="Virtual server actions">
                  <EllipsisVertical className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start">
                <DropdownMenuItem onClick={() => navigate("/app/servers?openForm=true")}>
                  Connect a source
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => navigate("/app/server-catalog")}>
                  Browse server catalog
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>

        {error && (
          <div
            className="rounded-lg border border-destructive/30 bg-destructive/10 p-4"
            role="alert"
          >
            <h2 className="font-semibold text-destructive">Error loading virtual servers</h2>
            <p className="text-sm text-destructive">{error.message}</p>
          </div>
        )}

        <div className="grid gap-6 lg:grid-cols-2">
          <ConnectSourceCard onAction={() => navigate("/app/servers?openForm=true")} />
          {servers.map((server) => (
            <VirtualServerCard key={server.id} server={server} onViewDetails={setDetailsServer} />
          ))}
        </div>

        <VirtualServerDetailsDrawer
          server={hydratedDetailsServer}
          isLoading={Boolean(detailsServer) && isServerDetailsLoading}
          error={serverDetailsError}
          onAddComponents={() => navigate("/app/servers?openForm=true")}
          onAddSources={() => navigate("/app/servers?openForm=true")}
          onOpenChange={(open) => {
            if (!open) setDetailsServer(null);
          }}
        />
      </div>
    );
  }

  return <SourceSelection actionCards={actionCards} />;
}
