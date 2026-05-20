import { useMemo, useState } from "react";
import { Blocks, Bot, Code, Plus } from "lucide-react";
import { MCPIcon } from "@/components/icons/MCPIcon";
import { ConnectSourceCard } from "@/components/gateways/ConnectSourceCard";
import { SourceSelection } from "@/components/gateways/SourceSelection";
import { VirtualServerCard } from "@/components/gateways/VirtualServerCard";
import { VirtualServerDetailsDrawer } from "@/components/gateways/VirtualServerDetailsDrawer";
import type { ActionCard } from "@/components/gateways/types";
import { Button } from "@/components/ui/button";
import { Loading } from "@/components/ui/loading";
import { useQuery } from "@/hooks/useQuery";
import { useRouter } from "@/router";
import type { VirtualServer, VirtualServersResponse } from "@/types/server";

const DEFAULT_PAGE_SIZE = 12;
const SERVERS_QUERY_PATH = `/servers?limit=${DEFAULT_PAGE_SIZE}&include_pagination=true`;

export function Gateways() {
  const { navigate } = useRouter();
  const { data, error, isLoading } = useQuery<VirtualServersResponse>(SERVERS_QUERY_PATH);
  const [detailsServer, setDetailsServer] = useState<VirtualServer | null>(null);
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
          <h1 className="text-base font-semibold text-foreground">Virtual servers</h1>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-7 gap-1.5 bg-background"
            onClick={() => navigate("/app/servers?openForm=true")}
          >
            <Plus className="size-3.5" />
            Create Server
          </Button>
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

        {detailsServer && (
          <VirtualServerDetailsDrawerContainer
            server={detailsServer}
            onAddComponents={() => navigate("/app/servers?openForm=true")}
            onAddSources={() => navigate("/app/servers?openForm=true")}
            onOpenChange={(open) => {
              if (!open) setDetailsServer(null);
            }}
          />
        )}
      </div>
    );
  }

  return <SourceSelection actionCards={actionCards} />;
}

function VirtualServerDetailsDrawerContainer({
  server,
  onAddComponents,
  onAddSources,
  onOpenChange,
}: {
  server: VirtualServer;
  onAddComponents: () => void;
  onAddSources: () => void;
  onOpenChange: (open: boolean) => void;
}) {
  const {
    data: serverDetails,
    error,
    isLoading,
  } = useQuery<VirtualServer>(`/servers/${encodeURIComponent(server.id)}`);
  const hydratedServer = serverDetails?.id === server.id ? serverDetails : server;

  return (
    <VirtualServerDetailsDrawer
      server={hydratedServer}
      isLoading={isLoading}
      error={error}
      onAddComponents={onAddComponents}
      onAddSources={onAddSources}
      onOpenChange={onOpenChange}
    />
  );
}
