import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useIntl } from "react-intl";
import { toast } from "sonner";
import { ConnectSourceCard } from "@/components/gateways/ConnectSourceCard";
import { VirtualServerCard } from "@/components/gateways/VirtualServerCard";
import { VirtualServerDetailsPanel } from "@/components/gateways/VirtualServerDetailsPanel";
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
const EDIT_SERVER_ID_QUERY_PARAM = "editServerId";

function sortServersForLayout(servers: VirtualServer[]): VirtualServer[] {
  return [...servers].sort(
    (a, b) => Number(hasVirtualServerComponents(b)) - Number(hasVirtualServerComponents(a)),
  );
}

export function Gateways() {
  const intl = useIntl();
  const { navigate, path } = useRouter();
  const { data, error, isLoading, refetch } = useQuery<VirtualServersResponse>(SERVERS_QUERY_PATH);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const pendingDeleteServerIdRef = useRef<string | null>(null);
  const [detailsServer, setDetailsServer] = useState<VirtualServer | null>(null);
  const [detailsServerId, setDetailsServerId] = useState<string | null>(null);
  const [isDetailsPanelOpen, setIsDetailsPanelOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteServer, setDeleteServer] = useState<VirtualServer | null>(null);
  const [deletedServerIds, setDeletedServerIds] = useState<Set<string>>(() => new Set());
  const [pendingDeleteServerId, setPendingDeleteServerId] = useState<string | null>(null);
  const servers = useMemo(
    () => (data?.servers ?? []).filter((server) => !deletedServerIds.has(server.id)),
    [data?.servers, deletedServerIds],
  );
  const layoutServers = useMemo(() => sortServersForLayout(servers), [servers]);
  const selectedSearchServerId = useMemo(() => {
    const queryString = path.split("?")[1] ?? "";
    return new URLSearchParams(queryString).get("selected")?.trim() || null;
  }, [path]);
  const isDeletePending = pendingDeleteServerId !== null;

  const handleDelete = useCallback(
    (server: VirtualServer) => {
      if (isDeletePending) return;
      setDeleteServer(server);
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
    const previousDetailsServer = detailsServer;
    const previousDetailsServerId = detailsServerId;
    pendingDeleteServerIdRef.current = serverToDelete.id;
    setPendingDeleteServerId(serverToDelete.id);
    // Close dialog and clear form state immediately
    setDeleteDialogOpen(false);
    setDeleteServer(null);
    // Remove the card from the grid right away for a snappy feel
    setDetailsServer((current) => (current?.id === serverToDelete.id ? null : current));
    setDetailsServerId((current) => (current === serverToDelete.id ? null : current));
    setDeletedServerIds((previous) => {
      const next = new Set(previous);
      next.add(serverToDelete.id);
      return next;
    });

    try {
      await deleteVirtualServer(serverToDelete.id);

      toast.success(
        intl.formatMessage({ id: "gateways.delete.success" }, { name: serverToDelete.name }),
      );
      try {
        await refetch();
      } catch (refreshErr) {
        console.error(
          "Failed to refresh virtual servers after deletion:",
          sanitizeError(refreshErr),
        );
      }
    } catch (err) {
      // ROLLBACK on failure
      setDeletedServerIds((previous) => {
        const next = new Set(previous);
        next.delete(serverToDelete.id);
        return next;
      });
      setDetailsServer(previousDetailsServer);
      setDetailsServerId(previousDetailsServerId);
      const errorMessage = sanitizeError(err);
      toast.error(intl.formatMessage({ id: "gateways.delete.errorTitle" }), {
        description: errorMessage,
      });
      console.error("Failed to delete virtual server:", errorMessage);
    } finally {
      pendingDeleteServerIdRef.current = null;
      setPendingDeleteServerId(null);
    }
  }, [deleteServer, detailsServer, detailsServerId, intl, refetch]);

  const openDetailsPanel = (server: VirtualServer) => {
    setDetailsServer(server);
    setDetailsServerId(server.id);
    setIsDetailsPanelOpen(true);
  };

  const openEditPanel = (server: VirtualServer) => {
    const params = new URLSearchParams({ [EDIT_SERVER_ID_QUERY_PARAM]: server.id });
    navigate(`${CREATE_SERVER_PATH}?${params.toString()}`);
  };

  useEffect(() => {
    if (!selectedSearchServerId) return;
    const seedServer = servers.find((server) => server.id === selectedSearchServerId) ?? null;
    setDetailsServer(seedServer);
    setDetailsServerId(selectedSearchServerId);
    setIsDetailsPanelOpen(true);
  }, [selectedSearchServerId, servers]);

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

  return (
    <div className="space-y-9 p-6">
      <h1 ref={headingRef} tabIndex={-1} className="text-base font-semibold text-foreground">
        {intl.formatMessage({ id: "gateways.title" })}
      </h1>

      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4" role="alert">
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
              onAddComponents={openEditPanel}
              onEdit={openEditPanel}
              onDelete={handleDelete}
              isDeleting={pendingDeleteServerId === server.id}
              deleteDisabled={isDeletePending && pendingDeleteServerId !== server.id}
              className={cn(!hasComponents && "col-span-full")}
            />
          );
        })}
      </div>

      {detailsServerId && (
        <VirtualServerDetailsPanelContainer
          serverId={detailsServerId}
          server={detailsServer}
          open={isDetailsPanelOpen}
          onClose={() => setIsDetailsPanelOpen(false)}
          onAddSources={(server) => openEditPanel(server)}
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

function VirtualServerDetailsPanelContainer({
  serverId,
  server,
  open,
  onClose,
  onAddSources,
}: {
  serverId: string;
  server: VirtualServer | null;
  open: boolean;
  onClose: () => void;
  onAddSources: (server: VirtualServer) => void;
}) {
  const { data: serverDetails, error } = useQuery<VirtualServer>(
    `/servers/${encodeURIComponent(serverId)}`,
  );
  const hydratedServer = serverDetails?.id === serverId ? serverDetails : server;

  if (!hydratedServer) {
    return null;
  }

  return (
    <VirtualServerDetailsPanel
      key={hydratedServer.id}
      server={hydratedServer}
      error={error}
      open={open}
      onClose={onClose}
      onAddSources={() => onAddSources(hydratedServer)}
    />
  );
}
