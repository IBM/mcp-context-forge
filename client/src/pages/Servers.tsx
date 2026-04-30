import { useState, useCallback, useMemo } from "react";
import { Plus } from "lucide-react";
import { MCPIcon } from "@/components/icons/MCPIcon";
import { Button } from "@/components/ui/button";
import { useRouter } from "@/router";
import { MCPServerForm } from "@/components/mcp-servers/MCPServerForm";
import { ServersTable } from "@/components/servers/ServersTable";
import { ConfirmDialog } from "@/components/servers/ConfirmDialog";
import { useQuery } from "@/hooks/useQuery";
import { serversApi } from "@/api/servers";
import { sanitizeError } from "@/utils/errors";
import type { PaginationMeta, ServersResponse } from "@/types/server";

// Pagination constants
const DEFAULT_PAGE_SIZE = 25;

export function Servers() {
  const { navigate } = useRouter();
  const [currentPage, setCurrentPage] = useState(1);
  const [perPage] = useState(DEFAULT_PAGE_SIZE);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [testDialogOpen, setTestDialogOpen] = useState(false);
  const [selectedServerId, setSelectedServerId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Build query path with pagination parameters
  const queryPath = useMemo(() => {
    const params = new URLSearchParams();
    params.set("page", currentPage.toString());
    params.set("per_page", perPage.toString());
    params.set("include_pagination", "true");
    return `/gateways?${params.toString()}`;
  }, [currentPage, perPage]);

  // Use useQuery hook for data fetching
  const {
    data: response,
    error: queryError,
    isLoading,
    refetch,
  } = useQuery<ServersResponse>(queryPath);

  // Derive servers and pagination from response
  const servers = response?.gateways ?? [];
  const pagination: PaginationMeta | null = response
    ? {
        page: currentPage,
        per_page: perPage,
        total: response.gateways.length,
        total_pages: 1,
      }
    : null;

  // Convert query error to string for display
  const error = queryError ? queryError.message : null;

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const handleEdit = (_id: string) => {
    // TODO: Implement edit functionality
    throw new Error("Edit functionality not yet implemented");
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
    try {
      const result = await serversApi.testConnection(id);
      setTestResult(result.message);
      setTestDialogOpen(true);
    } catch (err) {
      console.error("Failed to test connection:", sanitizeError(err));
    }
  };

  const handlePreviousPage = useCallback(() => {
    setCurrentPage((p) => Math.max(1, p - 1));
  }, []);

  const handleNextPage = useCallback(() => {
    setCurrentPage((p) => Math.min(pagination?.total_pages ?? 1, p + 1));
  }, [pagination?.total_pages]);

  // Initialize state based on URL parameter to avoid flicker
  const [isFormOpen, setIsFormOpen] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("openForm") === "true";
  });

  return (
    <div className="p-6">
      {isFormOpen ? (
        <MCPServerForm isOpen={isFormOpen} onToggle={() => setIsFormOpen(false)} />
      ) : isLoading ? (
        <div
          role="status"
          aria-live="polite"
          aria-busy="true"
          className="flex items-center justify-center p-12"
        >
          <span className="sr-only">Loading servers, please wait...</span>
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-gray-200 border-t-blue-600 dark:border-gray-700 dark:border-t-blue-400" />
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

          {servers.length > 0 ? (
            <>
              <div className="flex justify-between items-center mb-6">
                <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">
                  MCP Servers
                </h1>
                <Button
                  variant="default"
                  className="h-10 rounded-lg px-4"
                  onClick={() => setIsFormOpen(true)}
                >
                  <Plus className="h-4 w-4" />
                  New Server
                </Button>
              </div>

              <ServersTable
                servers={servers}
                isLoading={isLoading}
                onEdit={handleEdit}
                onDelete={handleDelete}
                onTest={handleTest}
              />

              {pagination && pagination.total_pages > 1 && (
                <nav
                  aria-label="Server list pagination"
                  className="flex items-center justify-between mt-6"
                >
                  <div className="text-sm text-gray-600 dark:text-gray-400">
                    Showing {(currentPage - 1) * perPage + 1} to{" "}
                    {Math.min(currentPage * perPage, pagination.total)} of {pagination.total}{" "}
                    servers
                  </div>
                  <div className="flex gap-2" role="group" aria-label="Pagination controls">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handlePreviousPage}
                      disabled={currentPage === 1}
                      aria-label={`Go to previous page (currently on page ${currentPage})`}
                    >
                      Previous
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handleNextPage}
                      disabled={currentPage === pagination.total_pages}
                      aria-label={`Go to next page (currently on page ${currentPage})`}
                    >
                      Next
                    </Button>
                  </div>
                </nav>
              )}
            </>
          ) : (
            <div className="rounded-2xl border border-neutral-200 bg-white p-8 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
              <div className="flex flex-col gap-6">
                <div className="flex items-center gap-3">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-sm bg-orange-500 text-white shadow-sm">
                    <MCPIcon className="h-5 w-5 [&_path]:fill-white" />
                  </div>
                  <h2 className="text-xl font-semibold text-neutral-950 dark:text-neutral-50">
                    Connect MCP server
                  </h2>
                </div>

                <p className="text-sm leading-relaxed text-neutral-600 dark:text-neutral-400">
                  Register an MCP server to federate its tools, resources, and prompts. Or,{" "}
                  <button
                    type="button"
                    onClick={() => navigate("/app/server-catalog")}
                    className="font-medium text-cyan-700 underline decoration-cyan-300 underline-offset-4 transition hover:text-cyan-800 dark:text-cyan-400 dark:decoration-cyan-700 dark:hover:text-cyan-300"
                  >
                    select from available servers
                  </button>
                  .
                </p>

                <Button
                  variant="default"
                  className="h-10 w-fit rounded-lg px-4"
                  onClick={() => setIsFormOpen(true)}
                >
                  <Plus className="h-4 w-4" />
                  Connect
                </Button>
              </div>
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
    </div>
  );
}
