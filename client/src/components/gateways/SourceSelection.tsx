import { useMemo, useState } from "react";
import { useIntl } from "react-intl";
import {
  Activity,
  ArrowLeft,
  Box,
  ChevronDown,
  ChevronRight,
  CircleSlash,
  Globe,
  Lock,
  MessageSquareCode,
  Plus,
  Shield,
  TriangleAlert,
  Wrench,
} from "lucide-react";
import { MainNavIcon } from "@/components/icons/MainNavIcon";
import { MCPIcon } from "@/components/icons/MCPIcon";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Loading } from "@/components/ui/loading";
import type { ActionCard } from "@/components/gateways/types";
import { useQuery } from "@/hooks/useQuery";
import type { MCPServer, ServerStatus } from "@/types/server";

const MCP_SERVERS_QUERY_PATH = "/gateways?limit=100&include_inactive=true";

type ListedMCPServer = MCPServer & {
  tool_count?: number;
  resource_count?: number;
  prompt_count?: number;
};

interface MCPServersResponse {
  gateways?: ListedMCPServer[];
  nextCursor?: string | null;
}

function getMCPServers(data: MCPServersResponse | ListedMCPServer[] | undefined) {
  if (Array.isArray(data)) return data;
  return data?.gateways ?? [];
}

function getMCPServerKeys(server: ListedMCPServer) {
  return [server.id, server.slug, server.name].filter((key): key is string => Boolean(key));
}

function getToolCount(server: ListedMCPServer) {
  return server.toolCount ?? server.tool_count ?? 0;
}

function getResourceCount(server: ListedMCPServer) {
  return server.resourceCount ?? server.resource_count ?? 0;
}

function getPromptCount(server: ListedMCPServer) {
  return server.promptCount ?? server.prompt_count ?? 0;
}

function getServerStatus(server: ListedMCPServer): ServerStatus {
  if (!server.enabled) return "draft";
  if (!server.reachable) return server.lastSeen ? "warning" : "offline";
  return "active";
}

function getStatusConfig(status: ServerStatus) {
  switch (status) {
    case "active":
      return {
        Icon: Activity,
        labelId: "gateways.source.status.active",
        className: "text-emerald-400",
      };
    case "warning":
      return {
        Icon: TriangleAlert,
        labelId: "gateways.source.status.warning",
        className: "text-amber-400",
      };
    case "offline":
      return {
        Icon: CircleSlash,
        labelId: "gateways.source.status.offline",
        className: "text-muted-foreground",
      };
    default:
      return {
        Icon: CircleSlash,
        labelId: "gateways.source.status.inactive",
        className: "text-muted-foreground",
      };
  }
}

function getVisibilityConfig(visibility: ListedMCPServer["visibility"]) {
  switch (visibility) {
    case "private":
      return { Icon: Lock, labelId: "gateways.createServer.visibility.private" };
    case "team":
      return { Icon: Shield, labelId: "gateways.createServer.visibility.team" };
    default:
      return { Icon: Globe, labelId: "gateways.createServer.visibility.public" };
  }
}

export function SourceSelection({
  actionCards,
  createServerActions,
  associatedMCPServerIds = [],
  onSelectSources,
}: {
  actionCards: ActionCard[];
  associatedMCPServerIds?: string[];
  onSelectSources?: (selectedIds: string[]) => void;
  createServerActions?: {
    onBack: () => void;
    onSkip: () => void;
    isSkipping?: boolean;
    skipError?: string | null;
  };
}) {
  const intl = useIntl();
  const firstEnabledIndex = actionCards.findIndex((card) => !card.disabled);
  const initialSelectedIndex = firstEnabledIndex === -1 ? 0 : firstEnabledIndex;
  const [selectedIndex, setSelectedIndex] = useState(initialSelectedIndex);
  const [isComponentsPanelOpen, setIsComponentsPanelOpen] = useState(false);
  const [hasRequestedMCPServers, setHasRequestedMCPServers] = useState(false);
  const [selectedMCPServerIds, setSelectedMCPServerIds] = useState<Set<string>>(new Set());
  const {
    data: mcpServersData,
    error: mcpServersError,
    isLoading: mcpServersLoading,
  } = useQuery<MCPServersResponse | ListedMCPServer[]>(MCP_SERVERS_QUERY_PATH, {
    enabled: Boolean(createServerActions) && hasRequestedMCPServers,
  });
  const mcpServers = useMemo(() => getMCPServers(mcpServersData), [mcpServersData]);
  const associatedMCPServerIdSet = useMemo(
    () => new Set(associatedMCPServerIds),
    [associatedMCPServerIds],
  );
  const availableMCPServers = useMemo(
    () =>
      mcpServers.filter(
        (server) => !getMCPServerKeys(server).some((key) => associatedMCPServerIdSet.has(key)),
      ),
    [associatedMCPServerIdSet, mcpServers],
  );
  const panelId = "connected-sources-panel";

  const handleToggleComponentsPanel = () => {
    setIsComponentsPanelOpen((open) => !open);
    setHasRequestedMCPServers(true);
  };

  const toggleMCPServerSelection = (serverId: string, checked: boolean) => {
    setSelectedMCPServerIds((current) => {
      const next = new Set(current);
      if (checked) next.add(serverId);
      else next.delete(serverId);
      onSelectSources?.(Array.from(next));
      return next;
    });
  };

  return (
    <div className="flex min-h-[calc(100vh-12rem)] items-center justify-center">
      <div className="w-full max-w-5xl space-y-12 px-6">
        {createServerActions && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={createServerActions.onBack}
            className="h-8 gap-2 px-0 text-sm font-medium text-foreground hover:bg-transparent hover:text-foreground"
          >
            <ArrowLeft className="size-4" aria-hidden="true" />
            {intl.formatMessage({ id: "common.button.back" })}
          </Button>
        )}

        <div className="flex items-center justify-center gap-3">
          <MainNavIcon className="h-10 w-10 text-neutral-900 dark:text-neutral-50" />
          <h1 className="text-3xl font-semibold text-neutral-900 dark:text-neutral-50">
            {intl.formatMessage({ id: "gateways.source.heading" })}
          </h1>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {actionCards.map((card, index) => {
            const IconComponent = card.icon;
            const isDisabled = Boolean(card.disabled);
            const isSelected = index === selectedIndex && !isDisabled;
            const cardClasses = isDisabled
              ? "group/action-card flex cursor-not-allowed flex-col opacity-60"
              : `group/action-card flex cursor-pointer flex-col transition-all hover:border-primary hover:shadow-md hover:ring-primary ${
                  isSelected ? "border-primary shadow-md ring-1 ring-primary" : ""
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

        {createServerActions && (
          <div className="space-y-7">
            <button
              type="button"
              onClick={handleToggleComponentsPanel}
              aria-expanded={isComponentsPanelOpen}
              aria-controls={panelId}
              className="flex min-h-20 w-full items-center gap-4 rounded-xl border border-border px-6 text-left transition hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background dark:border-[#252529]"
            >
              <span className="flex size-10 shrink-0 items-center justify-center rounded-md bg-muted text-foreground dark:bg-[#252529]">
                <Plus className="size-5" aria-hidden="true" />
              </span>
              <span className="min-w-0 flex-1 text-base font-semibold text-muted-foreground">
                {intl.formatMessage({ id: "gateways.source.addComponents" })}
              </span>
              {isComponentsPanelOpen ? (
                <ChevronDown className="size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
              ) : (
                <ChevronRight
                  className="size-5 shrink-0 text-muted-foreground"
                  aria-hidden="true"
                />
              )}
            </button>

            {isComponentsPanelOpen && (
              <section
                id={panelId}
                aria-labelledby="connected-sources-heading"
                className="rounded-xl border border-border bg-card p-5 dark:border-[#252529]"
              >
                <div className="flex items-center justify-between gap-4">
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-foreground dark:bg-[#252529]">
                      <MCPIcon className="size-5 [&_path]:fill-current" />
                    </span>
                    <h2
                      id="connected-sources-heading"
                      className="text-sm font-semibold text-foreground"
                    >
                      {intl.formatMessage({ id: "gateways.source.sources" })}
                    </h2>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="xs"
                    className="h-7 rounded-sm bg-background px-2 text-[13px]"
                    onClick={() => {
                      const firstEnabledCard = actionCards.find((card) => !card.disabled);
                      firstEnabledCard?.onAction();
                    }}
                  >
                    <Plus className="size-3" />
                    {intl.formatMessage({ id: "gateways.source.addSource" })}
                  </Button>
                </div>

                {mcpServersLoading && (
                  <div
                    role="status"
                    aria-live="polite"
                    className="flex items-center justify-center gap-2 py-10 text-muted-foreground"
                  >
                    <Loading />
                    <span>{intl.formatMessage({ id: "gateways.source.loadingSources" })}</span>
                  </div>
                )}

                {!mcpServersLoading && mcpServersError && (
                  <p
                    role="alert"
                    className="mt-5 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
                  >
                    {mcpServersError.message}
                  </p>
                )}

                {!mcpServersLoading && !mcpServersError && availableMCPServers.length === 0 && (
                  <p className="py-10 text-center text-sm text-muted-foreground">
                    {intl.formatMessage({ id: "gateways.source.emptySources" })}
                  </p>
                )}

                {!mcpServersLoading && !mcpServersError && availableMCPServers.length > 0 && (
                  <div className="mt-5 overflow-hidden">
                    <div className="grid grid-cols-[32px_minmax(180px,1fr)_minmax(220px,1fr)_120px_112px] gap-4 border-b border-border px-3 pb-3 text-xs font-medium text-muted-foreground">
                      <span className="sr-only">
                        {intl.formatMessage({ id: "gateways.source.selectColumn" })}
                      </span>
                      <span>{intl.formatMessage({ id: "common.name" })}</span>
                      <span>{intl.formatMessage({ id: "navigation.components" })}</span>
                      <span>{intl.formatMessage({ id: "gateways.details.visibility" })}</span>
                      <span>{intl.formatMessage({ id: "gateways.details.status" })}</span>
                    </div>
                    <div className="divide-y divide-border/60">
                      {availableMCPServers.map((server) => {
                        const toolCount = getToolCount(server);
                        const resourceCount = getResourceCount(server);
                        const promptCount = getPromptCount(server);
                        const visibility = getVisibilityConfig(server.visibility);
                        const VisibilityIcon = visibility.Icon;
                        const status = getStatusConfig(getServerStatus(server));
                        const StatusIcon = status.Icon;
                        const isSelected = selectedMCPServerIds.has(server.id);

                        return (
                          <div
                            key={server.id}
                            className="grid min-h-12 grid-cols-[32px_minmax(180px,1fr)_minmax(220px,1fr)_120px_112px] items-center gap-4 px-3 py-2 text-sm hover:bg-muted/30"
                          >
                            <Checkbox
                              checked={isSelected}
                              onCheckedChange={(checked) =>
                                toggleMCPServerSelection(server.id, checked === true)
                              }
                              aria-label={intl.formatMessage(
                                { id: "gateways.source.selectSource" },
                                { name: server.name },
                              )}
                            />
                            <div className="flex min-w-0 items-center gap-3">
                              <span className="flex size-6 shrink-0 items-center justify-center rounded-sm bg-primary text-primary-foreground">
                                <MCPIcon className="size-4 [&_path]:fill-current" />
                              </span>
                              <span className="min-w-0 truncate font-medium text-foreground">
                                {server.name}
                              </span>
                            </div>
                            <div className="flex min-w-0 items-center gap-3 text-muted-foreground">
                              <span className="flex items-center gap-1.5">
                                <Wrench className="size-3.5" />
                                {toolCount}
                              </span>
                              <span className="text-border">•</span>
                              <span className="flex items-center gap-1.5">
                                <Box className="size-3.5" />
                                {resourceCount}
                              </span>
                              <span className="text-border">•</span>
                              <span className="flex items-center gap-1.5">
                                <MessageSquareCode className="size-3.5" />
                                {promptCount}
                              </span>
                            </div>
                            <span className="flex min-w-0 items-center gap-2 text-muted-foreground">
                              <VisibilityIcon className="size-3.5" />
                              {intl.formatMessage({ id: visibility.labelId })}
                            </span>
                            <span className="flex min-w-0 items-center gap-2 text-muted-foreground">
                              <StatusIcon className={`size-3.5 ${status.className}`} />
                              {intl.formatMessage({ id: status.labelId })}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </section>
            )}

            <div className="flex justify-end">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={createServerActions.onSkip}
                disabled={createServerActions.isSkipping}
                className="h-8 rounded-md bg-background px-3 text-sm"
              >
                {createServerActions.isSkipping
                  ? intl.formatMessage({ id: "gateways.createServer.creating" })
                  : intl.formatMessage({ id: "gateways.source.skipForNow" })}
              </Button>
            </div>
            {createServerActions.skipError && (
              <p role="alert" className="text-right text-sm text-destructive">
                {createServerActions.skipError}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
