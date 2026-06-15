import { useMemo, useState } from "react";
import { useIntl } from "react-intl";
import { Blocks, Bot, Code } from "lucide-react";
import { MCPIcon } from "@/components/icons/MCPIcon";
import { ConnectSourceCard } from "@/components/gateways/ConnectSourceCard";
import { SourceSelection } from "@/components/gateways/SourceSelection";
import { VirtualServerCard } from "@/components/gateways/VirtualServerCard";
import { VirtualServerDetailsPanel } from "@/components/gateways/VirtualServerDetailsPanel";
import type { ActionCard } from "@/components/gateways/types";
import { hasVirtualServerComponents } from "@/components/gateways/utils";
import { Loading } from "@/components/ui/loading";
import { useQuery } from "@/hooks/useQuery";
import { useRouter } from "@/router";
import type { VirtualServer, VirtualServersResponse } from "@/types/server";
import { cn } from "@/lib/utils";

const DEFAULT_PAGE_SIZE = 12;
const SERVERS_QUERY_PATH = `/servers?limit=${DEFAULT_PAGE_SIZE}&include_pagination=true`;
const CREATE_SERVER_PATH = "/app/gateways/create-server";

function sortServersForLayout(servers: VirtualServer[]): VirtualServer[] {
  return [...servers].sort(
    (a, b) => Number(hasVirtualServerComponents(b)) - Number(hasVirtualServerComponents(a)),
  );
}

export function Gateways() {
  const intl = useIntl();
  const { navigate } = useRouter();
  const { data, error, isLoading } = useQuery<VirtualServersResponse>(SERVERS_QUERY_PATH);
  const [detailsServer, setDetailsServer] = useState<VirtualServer | null>(null);
  const [isDetailsPanelOpen, setIsDetailsPanelOpen] = useState(false);
  const servers = useMemo(() => data?.servers ?? [], [data?.servers]);
  const layoutServers = useMemo(() => sortServersForLayout(servers), [servers]);

  const openDetailsPanel = (server: VirtualServer) => {
    setDetailsServer(server);
    setIsDetailsPanelOpen(true);
  };

  const actionCards: ActionCard[] = useMemo(
    () => [
      {
        icon: MCPIcon,
        title: intl.formatMessage({ id: "gateways.action.mcpServer.title" }),
        description: intl.formatMessage({ id: "gateways.action.mcpServer.description" }),
        buttonText: intl.formatMessage({ id: "gateways.action.connect" }),
        onAction: () => navigate(CREATE_SERVER_PATH),
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
          <span className="sr-only">
            {intl.formatMessage({ id: "gateways.loadingVirtualServers" })}
          </span>
        </div>
      </div>
    );
  }

  if (error && servers.length === 0) {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4" role="alert">
          <h1 className="font-semibold text-destructive">
            {intl.formatMessage({ id: "gateways.errorLoadingVirtualServers" })}
          </h1>
          <p className="text-sm text-destructive">{error.message}</p>
        </div>
      </div>
    );
  }

  if (servers.length > 0) {
    return (
      <div className="space-y-9 p-6">
        <h1 className="text-base font-semibold text-foreground">
          {intl.formatMessage({ id: "gateways.title" })}
        </h1>

        {error && (
          <div
            className="rounded-lg border border-destructive/30 bg-destructive/10 p-4"
            role="alert"
          >
            <h2 className="font-semibold text-destructive">
              {intl.formatMessage({ id: "gateways.errorLoadingVirtualServers" })}
            </h2>
            <p className="text-sm text-destructive">{error.message}</p>
          </div>
        )}

        <div className="grid gap-6 lg:grid-cols-2">
          <ConnectSourceCard onAction={() => navigate(CREATE_SERVER_PATH)} />
          {layoutServers.map((server) => {
            const hasComponents = hasVirtualServerComponents(server);

            return (
              <VirtualServerCard
                key={server.id}
                server={server}
                onViewDetails={openDetailsPanel}
                onAddComponents={() => navigate(CREATE_SERVER_PATH)}
                className={cn(!hasComponents && "col-span-full")}
              />
            );
          })}
        </div>

        {detailsServer && (
          <VirtualServerDetailsPanelContainer
            server={detailsServer}
            open={isDetailsPanelOpen}
            onClose={() => setIsDetailsPanelOpen(false)}
            onAddSources={() => navigate(CREATE_SERVER_PATH)}
          />
        )}
      </div>
    );
  }

  return <SourceSelection actionCards={actionCards} />;
}

function VirtualServerDetailsPanelContainer({
  server,
  open,
  onClose,
  onAddSources,
}: {
  server: VirtualServer;
  open: boolean;
  onClose: () => void;
  onAddSources: () => void;
}) {
  const { data: serverDetails, error } = useQuery<VirtualServer>(
    `/servers/${encodeURIComponent(server.id)}`,
  );
  const hydratedServer = serverDetails?.id === server.id ? serverDetails : server;

  return (
    <VirtualServerDetailsPanel
      key={hydratedServer.id}
      server={hydratedServer}
      error={error}
      open={open}
      onClose={onClose}
      onAddSources={onAddSources}
    />
  );
}
