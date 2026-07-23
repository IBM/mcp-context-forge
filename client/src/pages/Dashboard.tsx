import { useMemo } from "react";
import { useIntl } from "react-intl";
import { Blocks, Bot, Code } from "lucide-react";
import { SourceSelection } from "@/components/gateways/SourceSelection";
import type { ActionCard } from "@/components/gateways/types";
import { MCPIcon } from "@/components/icons/MCPIcon";
import { Loading } from "@/components/ui/loading";
import { useQuery } from "@/hooks/useQuery";
import { useRouter } from "@/router";
import type { VirtualServersResponse } from "@/types/server";

const SERVERS_QUERY_PATH = "/servers?limit=1&include_pagination=true";
const MCP_SERVERS_QUERY_PATH = "/gateways?limit=1&include_inactive=true&include_pagination=true";
const SERVERS_FORM_PATH = "/app/servers?openForm=true";

interface MCPServersResponse {
  gateways?: unknown[];
}

export function Dashboard() {
  const intl = useIntl();
  const { navigate } = useRouter();
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

  if (!hasVirtualServers && !hasMCPServers) {
    return <SourceSelection actionCards={actionCards} />;
  }

  return (
    <div className="space-y-9 p-6">
      <h1 className="text-xl font-semibold text-neutral-900 dark:text-neutral-100">
        {intl.formatMessage({ id: "dashboard.title" })}
      </h1>
    </div>
  );
}
