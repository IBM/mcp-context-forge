import { useMemo } from "react";
import { useIntl } from "react-intl";
import { Blocks, Bot, Code } from "lucide-react";
import { SourceSelection } from "@/components/gateways/SourceSelection";
import type { ActionCard } from "@/components/gateways/types";
import { MCPIcon } from "@/components/icons/MCPIcon";
import { ActivityFeedButton } from "@/components/dashboard/ActivityFeedButton";
import { ClearControl } from "@/components/dashboard/ClearControl";
import { EmptyStatePlaceholder } from "@/components/dashboard/EmptyStatePlaceholder";
import { McpHealthCard } from "@/components/dashboard/McpHealthCard";
import { MiniCard } from "@/components/dashboard/MiniCard";
import { MiniCardStatusIndicator } from "@/components/dashboard/MiniCardStatusIndicator";
import type { MiniCardStatus } from "@/components/dashboard/miniCardStatus";
import { PermissionDenied } from "@/components/dashboard/PermissionDenied";
import type { HeadlineCondition } from "@/components/dashboard/resolveHeadline";
import { useMiniCardStatuses } from "@/hooks/useMiniCardStatuses";
import type { SystemHealthResult } from "@/hooks/useSystemHealth";
import { StatusHeadline } from "@/components/dashboard/StatusHeadline";
import { SystemStatsCardConnected } from "@/components/dashboard/SystemStatsCardConnected";
import { SystemView } from "@/components/dashboard/SystemView";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/auth/useAuth";
import {
  HOME_STATES,
  getRightColumnCards,
  getViewIcon,
  readActiveView,
  type HomeViewId,
  type MiniCardId,
} from "@/components/dashboard/homeStates";
import { Loading } from "@/components/ui/loading";
import { useQuery } from "@/hooks/useQuery";
import { useRouter } from "@/router";
import type { VirtualServersResponse } from "@/types/server";

const SERVERS_QUERY_PATH = "/servers?limit=1&include_pagination=true";
const MCP_SERVERS_QUERY_PATH = "/gateways?limit=1&include_inactive=true&include_pagination=true";
const SERVERS_FORM_PATH = "/app/servers?openForm=true";

/** Inline source cards shown in the default state (one per source type). */
const DEFAULT_SOURCE_CARDS: MiniCardId[] = ["mcp", "a2a", "rest", "grpc"];

interface MCPServersResponse {
  gateways?: unknown[];
}

export function Dashboard() {
  const intl = useIntl();
  const { path, navigate } = useRouter();
  const activeView = readActiveView(path);

  const {
    data: virtualServersData,
    error: virtualServersError,
    isLoading: virtualServersLoading,
  } = useQuery<VirtualServersResponse>(SERVERS_QUERY_PATH);
  const {
    data: mcpServersData,
    error: mcpServersError,
    isLoading: mcpServersLoading,
  } = useQuery<MCPServersResponse>(MCP_SERVERS_QUERY_PATH);

  // Resolved once at the page level (which stays mounted across ?view= changes)
  // so switching states does not remount the queries and flash stale statuses.
  const { statuses: miniCardStatuses, headlineCondition, systemHealth } = useMiniCardStatuses();

  const actionCards: ActionCard[] = useMemo(
    () => [
      {
        icon: MCPIcon,
        title: intl.formatMessage({ id: "gateways.action.mcpServer.title" }),
        description: intl.formatMessage({ id: "gateways.action.mcpServer.description" }),
        buttonText: intl.formatMessage({ id: "gateways.action.connect" }),
        onAction: () => navigate(SERVERS_FORM_PATH),
      },
      {
        icon: Bot,
        title: intl.formatMessage({ id: "gateways.action.aiAgent.title" }),
        description: intl.formatMessage({ id: "gateways.action.aiAgent.description" }),
        buttonText: intl.formatMessage({ id: "gateways.action.connect" }),
        onAction: () => navigate("/app/agents"),
      },
      {
        icon: Code,
        title: intl.formatMessage({ id: "gateways.action.restApi.title" }),
        description: intl.formatMessage({ id: "gateways.action.restApi.description" }),
        buttonText: intl.formatMessage({ id: "gateways.action.connect" }),
        disabled: true,
        disabledReason: intl.formatMessage({ id: "gateways.action.comingSoon" }),
        onAction: () => undefined,
      },
      {
        icon: Blocks,
        title: intl.formatMessage({ id: "gateways.action.grpc.title" }),
        description: intl.formatMessage({ id: "gateways.action.grpc.description" }),
        buttonText: intl.formatMessage({ id: "gateways.action.connect" }),
        disabled: true,
        disabledReason: intl.formatMessage({ id: "gateways.action.comingSoon" }),
        onAction: () => undefined,
      },
    ],
    [intl, navigate],
  );

  if (virtualServersLoading || mcpServersLoading) {
    return <Loading />;
  }

  const queryError = virtualServersError ?? mcpServersError;
  if (queryError) {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4" role="alert">
          <h1 className="font-semibold text-destructive">
            {intl.formatMessage({ id: "dashboard.errorLoadingSources" })}
          </h1>
          <p className="text-sm text-destructive">{queryError.message}</p>
        </div>
      </div>
    );
  }

  const hasVirtualServers = (virtualServersData?.servers?.length ?? 0) > 0;
  const hasMCPServers = (mcpServersData?.gateways?.length ?? 0) > 0;

  // Onboarding: no sources yet -> show the source-selection flow instead of the home.
  if (!hasVirtualServers && !hasMCPServers) {
    return <SourceSelection actionCards={actionCards} />;
  }

  return (
    <div className="p-6">
      {activeView === "default" ? (
        <DefaultState statuses={miniCardStatuses} headlineCondition={headlineCondition} />
      ) : (
        <NonDefaultState
          active={activeView}
          statuses={miniCardStatuses}
          systemHealth={systemHealth}
        />
      )}
    </div>
  );
}

/**
 * Default (resting) state: status summary with the activity-feed entry point,
 * the all-time system stats card, and the inline source cards. No right column.
 */
function DefaultState({
  statuses,
  headlineCondition,
}: {
  statuses: Record<MiniCardId, MiniCardStatus>;
  headlineCondition: HeadlineCondition;
}) {
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <StatusHeadline condition={headlineCondition} action={<ActivityFeedButton />} />
      <SystemStatsCardConnected />
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {DEFAULT_SOURCE_CARDS.map((id) => (
          <MiniCard key={id} id={id} status={<MiniCardStatusIndicator status={statuses[id]} />} />
        ))}
      </div>
    </div>
  );
}

/**
 * Any non-default state: main content (title + Clear control + the view's main
 * content, a placeholder for now) plus the right-column mini-card stack (the six
 * cards minus the active one).
 */
function NonDefaultState({
  active,
  statuses,
  systemHealth,
}: {
  active: HomeViewId;
  statuses: Record<MiniCardId, MiniCardStatus>;
  systemHealth: SystemHealthResult;
}) {
  const intl = useIntl();
  const { hasPermission, permissionsLoading } = useAuth();
  const state = HOME_STATES[active];
  const rightColumnCards = getRightColumnCards(active);
  const TitleIcon = getViewIcon(active);

  const gated = Boolean(state.requiredPermission);
  const allowed = !state.requiredPermission || hasPermission(state.requiredPermission);

  return (
    <div className="mx-auto grid max-w-5xl grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_260px]">
      <div className="min-w-0 space-y-4">
        <div className="flex items-center justify-between gap-4">
          <h1 className="flex items-center gap-2 font-heading text-lg font-medium text-foreground">
            {TitleIcon && <TitleIcon className="size-5 shrink-0 text-status-icon" />}
            {state.titleId ? intl.formatMessage({ id: state.titleId }) : null}
          </h1>
          <ClearControl />
        </div>
        {/* Gate the render on real permissions (never is_admin). Skeleton while
            permissions load to avoid a flash; PermissionDenied when disallowed.
            Real content (#5841/#5842/#5531/#5942/#5943) swaps in per view. */}
        {gated && permissionsLoading ? (
          <Skeleton className="h-40 w-full rounded-lg" />
        ) : allowed ? (
          <MainContent active={active} systemHealth={systemHealth} />
        ) : (
          <PermissionDenied />
        )}
      </div>
      <aside className="flex flex-col gap-3">
        {rightColumnCards.map((id) => (
          <MiniCard key={id} id={id} status={<MiniCardStatusIndicator status={statuses[id]} />} />
        ))}
      </aside>
    </div>
  );
}

/**
 * Main content per view. Real cards swap in here as they land; the rest render a
 * labeled placeholder. This is the per-view swap point the card PRs target.
 */
function MainContent({
  active,
  systemHealth,
}: {
  active: HomeViewId;
  systemHealth: SystemHealthResult;
}) {
  if (active === "system") return <SystemView />;
  if (active === "mcp") return <McpHealthCard health={systemHealth} />;
  return <EmptyStatePlaceholder messageId={PLACEHOLDER_MESSAGE[active]} />;
}

/** Placeholder copy per view until the real card lands. */
const PLACEHOLDER_MESSAGE: Record<HomeViewId, string> = {
  default: "dashboard.home.emptyState",
  activity: "dashboard.home.placeholder.activity",
  mcp: "dashboard.home.placeholder.mcp",
  a2a: "dashboard.home.placeholder.a2a",
  rest: "dashboard.home.placeholder.rest",
  grpc: "dashboard.home.placeholder.grpc",
  system: "dashboard.home.placeholder.system",
};
