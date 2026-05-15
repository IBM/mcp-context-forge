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
import { Blocks, Bot, Box, Code, EllipsisVertical, Plus, Upload, Wrench } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useQuery } from "@/hooks/useQuery";
import type { VirtualServer, VirtualServersResponse } from "@/types/server";
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

function formatServerTimestamp(value?: string) {
  if (!value) return "Not synced yet";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
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

function VirtualServerCard({ server }: { server: VirtualServer }) {
  const toolCount = server.associatedToolIds?.length ?? 0;
  const resourceCount = server.associatedResources?.length ?? 0;
  const promptCount = server.associatedPrompts?.length ?? 0;
  const tags = server.tags ?? [];

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
                <DropdownMenuItem disabled>View details</DropdownMenuItem>
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
                key={tag}
                variant="outline"
                className="shrink-0 px-1.5 py-0 text-[10px] font-medium text-muted-foreground"
              >
                {tag}
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
  const servers = data?.servers ?? [];

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
            <VirtualServerCard key={server.id} server={server} />
          ))}
        </div>
      </div>
    );
  }

  return <SourceSelection actionCards={actionCards} />;
}
