import { useState, useCallback, useMemo, useEffect } from "react";
import { Plus } from "lucide-react";
import { MCPIcon } from "@/components/icons/MCPIcon";
import { Button } from "@/components/ui/button";
import { MCPServerForm } from "@/components/mcp-servers/MCPServerForm";
import { ServersTable } from "@/components/servers/ServersTable";
import { ConfirmDialog } from "@/components/servers/ConfirmDialog";
import { MCPServerDetailsPanel } from "@/components/servers/MCPServerDetailsPanel";
import { useQuery } from "@/hooks/useQuery";
import { api } from "@/api/client";
import { serversApi } from "@/api/servers";
import { sanitizeError } from "@/utils/errors";
import type { MCPServer, ServersResponse } from "@/types/server";
import { Loading } from "@/components/ui/loading";
import { InlineNotification } from "@/components/ui/inline-notification";

// Pagination constants
const DEFAULT_PAGE_SIZE = 10;

export function Servers() {
  const [limit, setLimit] = useState(DEFAULT_PAGE_SIZE);
  const [allServers, setAllServers] = useState<MCPServer[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [testDialogOpen, setTestDialogOpen] = useState(false);
  const [selectedServerId, setSelectedServerId] = useState<string | null>(null);
  const [updateServerId, setUpdateServerId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [toggleError, setToggleError] = useState<string | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [selectedServerIdForDetails, setSelectedServerIdForDetails] = useState<string | null>(null);
  const [isDetailsDrawerOpen, setIsDetailsDrawerOpen] = useState(false);

  // Keep the primary list in sync with the selected page size
  const queryPath = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", limit.toString());
    params.set("include_pagination", "true");
    params.set("include_inactive", "true");
    return `/gateways?${params.toString()}`;
  }, [limit]);

  // Use useQuery hook for initial data fetching and limit changes
  const {
    data: response,
    error: queryError,
    isLoading,
    refetch,
  } = useQuery<ServersResponse>(queryPath);

  // Fetch server details when selectedServerIdForDetails changes
  const detailsQueryPath = useMemo(
    () =>
      selectedServerIdForDetails
        ? `/gateways/${encodeURIComponent(selectedServerIdForDetails)}`
        : "/gateways/_placeholder_",
    [selectedServerIdForDetails],
  );

  const { data: detailsServer, error: detailsQueryError } = useQuery<MCPServer>(detailsQueryPath, {
    enabled: Boolean(selectedServerIdForDetails),
  });

  const detailsError = detailsQueryError ? { message: detailsQueryError.message } : null;

  // Seed the panel from the listing row so the chrome renders instantly;
  // detailsServer silently replaces the seed once the detail fetch resolves.
  const selectedRow = useMemo(
    () => allServers.find((s) => s.id === selectedServerIdForDetails) ?? null,
    [allServers, selectedServerIdForDetails],
  );
  const panelServer = detailsServer ?? selectedRow;

  // Update servers on initial load
  useEffect(() => {
    if (response) {
      setAllServers(response.gateways);
      setNextCursor(response.nextCursor ?? null);
    }
  }, [response]);

  // Derive servers from accumulated list
  const servers = allServers;

  // Convert query error to string for display
  const error = queryError ? queryError.message : null;

  const handleEdit = (id: string) => {
    setUpdateServerId(id);
    setIsFormOpen(true);
  };

  const handleDelete = (id: string) => {
    setSelectedServerId(id);
    setDeleteDialogOpen(true);
  };

  const confirmDelete = async () => {
    if (!selectedServerId) return;

    setDeleteDialogOpen(false);
    setDeleteError(null);

    try {
      await serversApi.delete(selectedServerId);
      setSelectedServerId(null);
      await refetch();
    } catch (err) {
      const errorMsg = sanitizeError(err);
      setDeleteError(errorMsg);
      console.error("Failed to delete server:", errorMsg);
    }
  };

  const handleTest = async (id: string) => {
    setTestError(null);
    try {
      const result = await serversApi.testConnection(id);
      setTestResult(result.message);
      setTestDialogOpen(true);
    } catch (err) {
      const errorMsg = sanitizeError(err);
      setTestError(errorMsg);
      console.error("Failed to test connection:", errorMsg);
    }
  };

  const handleToggleEnabled = useCallback(
    async (id: string, enabled: boolean) => {
      setToggleError(null);
      try {
        await serversApi.toggleEnabled(id, enabled);
        await refetch();
      } catch (err) {
        const errorMsg = sanitizeError(err);
        setToggleError(errorMsg);
        console.error("Failed to toggle server state:", errorMsg);
      }
    },
    [refetch],
  );

  const handleViewDetails = useCallback((id: string) => {
    setSelectedServerIdForDetails(id);
    setIsDetailsDrawerOpen(true);
  }, []);

  const handleCloseDetails = useCallback((open: boolean) => {
    if (!open) {
      setIsDetailsDrawerOpen(false);
      setSelectedServerIdForDetails(null);
    }
  }, []);

  const handleLoadMore = useCallback(async () => {
    if (!nextCursor || loadingMore) return;

    setLoadingMore(true);
    try {
      const params = new URLSearchParams();
      params.set("cursor", nextCursor);
      params.set("limit", limit.toString());
      params.set("include_pagination", "true");
      params.set("include_inactive", "true");

      const result = await api.get<ServersResponse>(`/gateways?${params.toString()}`);
      setAllServers((prev) => [...prev, ...result.gateways]);
      setNextCursor(result.nextCursor ?? null);
    } catch (err) {
      console.error("Failed to load more servers:", err);
    } finally {
      setLoadingMore(false);
    }
  }, [nextCursor, limit, loadingMore]);

  const handleLimitChange = useCallback((newLimit: number) => {
    setLimit(newLimit);
  }, []);

  // Initialize state based on URL parameter to avoid flicker
  const [isFormOpen, setIsFormOpen] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("openForm") === "true";
  });

  return (
    <div className="p-6">
      {isFormOpen ? (
        <MCPServerForm
          isOpen={isFormOpen}
          onToggle={() => {
            setIsFormOpen(false);
            setUpdateServerId(null);
          }}
          serverId={updateServerId || undefined}
          onSuccess={() => {
            setIsFormOpen(false);
            setUpdateServerId(null);
            refetch();
          }}
        />
      ) : isLoading ? (
        <div
          role="status"
          aria-live="polite"
          aria-busy="true"
          className="flex items-center justify-center p-12"
        >
          <Loading />
          <span className="sr-only">Loading servers, please wait...</span>
        </div>
      ) : (
        <>
          {error && (
            <div
              className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 mb-6"
              role="alert"
              aria-live="assertive"
              aria-atomic="true"
            >
              <h3 className="font-semibold mb-1">Error loading servers</h3>
              <p className="text-red-800 dark:text-red-200">{error}</p>
            </div>
          )}

          {deleteError && (
            <div
              className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 mb-6"
              role="alert"
              aria-live="assertive"
              aria-atomic="true"
            >
              <h3 className="font-semibold mb-1">Error deleting server</h3>
              <p className="text-red-800 dark:text-red-200">{deleteError}</p>
            </div>
          )}

          {toggleError && (
            <div className="mb-6">
              <InlineNotification
                type="error"
                message={toggleError}
                onDismiss={() => setToggleError(null)}
              />
            </div>
          )}

          {testError && (
            <div className="mb-6">
              <InlineNotification
                type="error"
                message={testError}
                onDismiss={() => setTestError(null)}
              />
            </div>
          )}

          {servers.length > 0 ? (
            <>
              <div className="flex justify-between items-center mb-6">
                <h1 className="text-base font-semibold text-foreground">MCP Servers</h1>
                <Button
                  variant="default"
                  className="h-7 rounded-sm px-4"
                  onClick={() => setIsFormOpen(true)}
                >
                  <Plus className="h-4 w-4" />
                  Connect
                </Button>
              </div>

              <ServersTable
                servers={servers}
                isLoading={isLoading}
                onEdit={handleEdit}
                onDelete={handleDelete}
                onTest={handleTest}
                onViewDetails={handleViewDetails}
                onToggleEnabled={handleToggleEnabled}
              />

              <div className="flex items-center justify-between mt-6">
                <div className="flex items-center gap-4">
                  <div className="text-sm text-gray-600 dark:text-gray-400">
                    Showing {servers.length} server{servers.length !== 1 ? "s" : ""}
                  </div>
                  <div className="flex items-center gap-2">
                    <label
                      htmlFor="limit-select"
                      className="text-sm text-gray-600 dark:text-gray-400"
                    >
                      Per page:
                    </label>
                    <select
                      id="limit-select"
                      value={limit}
                      onChange={(e) => handleLimitChange(Number(e.target.value))}
                      className="rounded-md border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1 text-sm"
                    >
                      <option value={10}>10</option>
                      <option value={25}>25</option>
                      <option value={50}>50</option>
                      <option value={100}>100</option>
                    </select>
                  </div>
                </div>
                {nextCursor && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleLoadMore}
                    disabled={loadingMore}
                    aria-label="Load more servers"
                  >
                    {loadingMore ? "Loading..." : "Load More"}
                  </Button>
                )}
              </div>
            </>
          ) : (
            <div className="border border-border rounded-lg p-6 flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <div className="flex size-6 shrink-0 items-center justify-center rounded-sm bg-orange-500">
                  <MCPIcon className="size-4 [&_path]:fill-black" />
                </div>
                <h2 className="text-base font-medium">Connect MCP server</h2>
              </div>

              <div className="py-5">
                <p className="text-sm text-foreground">
                  Register a MCP server to federate its tools, resources, and prompts to use with a
                  virtual server.
                </p>
              </div>

              <Button
                className="bg-foreground text-background hover:bg-foreground/90 h-8 w-38 rounded-sm px-2 gap-1.5 text-sm font-medium"
                onClick={() => setIsFormOpen(true)}
              >
                <Plus className="size-3" />
                Connect
              </Button>
            </div>
          )}
        </>
      )}

      <ConfirmDialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        title="Delete MCP Server"
        description="Are you sure you want to delete this MCP server? This action cannot be undone."
        confirmLabel="Delete"
        cancelLabel="Cancel"
        variant="destructive"
        onConfirm={confirmDelete}
      />

      <ConfirmDialog
        open={testDialogOpen}
        onOpenChange={setTestDialogOpen}
        title="Connection Test Result"
        description={testResult || "Testing connection..."}
        confirmLabel="OK"
        cancelLabel=""
        onConfirm={() => setTestDialogOpen(false)}
      />

      <MCPServerDetailsPanel
        server={panelServer}
        error={detailsError}
        open={isDetailsDrawerOpen}
        onClose={() => handleCloseDetails(false)}
      />
    </div>
  );
}
