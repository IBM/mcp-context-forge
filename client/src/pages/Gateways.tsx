import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useIntl } from "react-intl";
import { toast } from "sonner";
import { Blocks, Bot, Code } from "lucide-react";
import { MCPIcon } from "@/components/icons/MCPIcon";
import { ConnectSourceCard } from "@/components/gateways/ConnectSourceCard";
import { SourceSelection } from "@/components/gateways/SourceSelection";
import { VirtualServerCard } from "@/components/gateways/VirtualServerCard";
import { VirtualServerDetailsPanel } from "@/components/gateways/VirtualServerDetailsPanel";
import type { ActionCard } from "@/components/gateways/types";
import { hasVirtualServerComponents } from "@/components/gateways/utils";
import { ConfirmDialog } from "@/components/servers/ConfirmDialog";
import { Loading } from "@/components/ui/loading";
import { deleteVirtualServer } from "@/api/virtualServers";
import { useQuery } from "@/hooks/useQuery";
import { useRouter } from "@/router";
import type { VirtualServer, VirtualServersResponse } from "@/types/server";
import { cn } from "@/lib/utils";
import { sanitizeError } from "@/utils/errors";

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
  const { data, error, isLoading, refetch } = useQuery<VirtualServersResponse>(SERVERS_QUERY_PATH);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const statusRef = useRef<HTMLDivElement>(null);
  const pendingDeleteServerIdRef = useRef<string | null>(null);
  const [detailsServer, setDetailsServer] = useState<VirtualServer | null>(null);
  const [isDetailsPanelOpen, setIsDetailsPanelOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteServer, setDeleteServer] = useState<VirtualServer | null>(null);
  const [deletedServerIds, setDeletedServerIds] = useState<Set<string>>(() => new Set());
  const [pendingDeleteServerId, setPendingDeleteServerId] = useState<string | null>(null);
  const [deleteStatus, setDeleteStatus] = useState<string | null>(null);
  const servers = useMemo(
    () => (data?.servers ?? []).filter((server) => !deletedServerIds.has(server.id)),
    [data?.servers, deletedServerIds],
  );
  const layoutServers = useMemo(() => sortServersForLayout(servers), [servers]);
  const isDeletePending = pendingDeleteServerId !== null;

  useEffect(() => {
    if (!deleteStatus) return;
    (headingRef.current ?? statusRef.current)?.focus();
  }, [deleteStatus]);

  const handleDelete = useCallback(
    (server: VirtualServer) => {
      if (isDeletePending) return;
      setDeleteServer(server);
      setDeleteStatus(null);
      setDeleteDialogOpen(true);
    },
    [isDeletePending],
  );

  const handleDeleteDialogOpenChange = useCallback((open: boolean) => {
    setDeleteDialogOpen(open);
    if (!open) {
      setDeleteServer(null);
    }
  }, []);

  const confirmDelete = useCallback(async () => {
    if (!deleteServer || pendingDeleteServerIdRef.current) return;

    const serverToDelete = deleteServer;
    const deletedMessage = intl.formatMessage(
      { id: "gateways.delete.success" },
      { name: serverToDelete.name },
    );

    pendingDeleteServerIdRef.current = serverToDelete.id;
    setPendingDeleteServerId(serverToDelete.id);
    setDeleteStatus(null);

    try {
      await deleteVirtualServer(serverToDelete.id);
      setDeletedServerIds((previous) => {
        const next = new Set(previous);
        next.add(serverToDelete.id);
        return next;
      });
      setDetailsServer((current) => (current?.id === serverToDelete.id ? null : current));
      setDeleteStatus(deletedMessage);
      setDeleteDialogOpen(false);
      setDeleteServer(null);
      try {
        await refetch();
      } catch (refreshErr) {
        console.error(
          "Failed to refresh virtual servers after deletion:",
          sanitizeError(refreshErr),
        );
      }
    } catch (err) {
      const errorMessage = sanitizeError(err);
      toast.error(intl.formatMessage({ id: "gateways.delete.errorTitle" }), {
        description: errorMessage,
      });
      setDeleteDialogOpen(false);
      setDeleteServer(null);
      console.error("Failed to delete virtual server:", errorMessage);
    } finally {
      pendingDeleteServerIdRef.current = null;
      setPendingDeleteServerId(null);
    }
  }, [deleteServer, intl, refetch]);

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
        <div
          ref={statusRef}
          tabIndex={-1}
          className="sr-only"
          role="status"
          aria-label={intl.formatMessage({ id: "gateways.notifications" })}
          aria-live="polite"
          aria-atomic="true"
        >
          {deleteStatus}
        </div>

        <h1 ref={headingRef} tabIndex={-1} className="text-base font-semibold text-foreground">
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
                onDelete={handleDelete}
                isDeleting={pendingDeleteServerId === server.id}
                deleteDisabled={isDeletePending && pendingDeleteServerId !== server.id}
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

        <ConfirmDialog
          open={deleteDialogOpen}
          onOpenChange={handleDeleteDialogOpenChange}
          title={intl.formatMessage({ id: "gateways.delete.title" })}
          description={intl.formatMessage(
            { id: "gateways.delete.description" },
            { name: deleteServer?.name ?? intl.formatMessage({ id: "gateways.title" }) },
          )}
          confirmLabel={intl.formatMessage({ id: "common.button.delete" })}
          cancelLabel={intl.formatMessage({ id: "common.button.cancel" })}
          variant="destructive"
          onConfirm={confirmDelete}
          isLoading={pendingDeleteServerId === deleteServer?.id}
          loadingLabel={intl.formatMessage({ id: "gateways.delete.deleting" })}
          closeOnConfirm={false}
        />
      </div>
    );
  }

  return (
    <>
      <div
        ref={statusRef}
        tabIndex={-1}
        className="sr-only"
        role="status"
        aria-label={intl.formatMessage({ id: "gateways.notifications" })}
        aria-live="polite"
        aria-atomic="true"
      >
        {deleteStatus}
      </div>
      <SourceSelection actionCards={actionCards} />
    </>
  );
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
