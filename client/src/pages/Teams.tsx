import { useState, useCallback, useMemo, useEffect } from "react";
import { useIntl } from "react-intl";
import { toast } from "sonner";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { TeamsTable } from "@/components/teams/TeamsTable";
import { TeamForm } from "@/components/teams/TeamForm";
import { ConfirmDialog } from "@/components/servers/ConfirmDialog";
import { ManageTeamMembersDialog } from "@/components/teams/ManageTeamMembersDialog";
import { useQuery } from "@/hooks/useQuery";
import { api } from "@/api/client";
import { deleteTeam } from "@/api/teams";
import type { Team, TeamsResponse } from "@/types/team";
import { sanitizeError } from "@/utils/errors";

const DEFAULT_PAGE_SIZE = 10;

export function Teams() {
  const intl = useIntl();
  const [limit, setLimit] = useState(DEFAULT_PAGE_SIZE);
  const [allTeams, setAllTeams] = useState<Team[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [teamToDelete, setTeamToDelete] = useState<Team | null>(null);
  const [createFormOpen, setCreateFormOpen] = useState(false);
  const [membersDialogOpen, setMembersDialogOpen] = useState(false);
  const [teamForMembers, setTeamForMembers] = useState<Team | null>(null);
  const [teamToEdit, setTeamToEdit] = useState<Team | null>(null);

  const queryPath = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", limit.toString());
    return `/teams?${params.toString()}`;
  }, [limit]);

  const {
    data: response,
    error: queryError,
    isLoading,
    refetch,
  } = useQuery<TeamsResponse>(queryPath);

  useEffect(() => {
    if (response) {
      setAllTeams(response.teams);
      setNextCursor(response.nextCursor ?? null);
    }
  }, [response]);

  const error = queryError ? queryError.message : null;

  const handleLoadMore = useCallback(async () => {
    if (!nextCursor || loadingMore) return;

    setLoadingMore(true);
    try {
      const params = new URLSearchParams();
      params.set("cursor", nextCursor);
      params.set("limit", limit.toString());

      const result = await api.get<TeamsResponse>(`/teams?${params.toString()}`);
      setAllTeams((prev) => [...prev, ...result.teams]);
      setNextCursor(result.nextCursor ?? null);
    } catch {
      toast.error(intl.formatMessage({ id: "teams.error.loadMore" }));
    } finally {
      setLoadingMore(false);
    }
  }, [nextCursor, limit, loadingMore, intl]);

  const handleLimitChange = useCallback((newLimit: number) => {
    setLimit(newLimit);
  }, []);

  const handleDelete = useCallback(
    (teamId: string) => {
      const team = allTeams.find((t) => t.id === teamId);
      if (team) {
        setTeamToDelete(team);
        setDeleteDialogOpen(true);
      }
    },
    [allTeams],
  );

  const handleManageMembers = useCallback(
    (teamId: string) => {
      const team = allTeams.find((t) => t.id === teamId);
      if (team) {
        setTeamForMembers(team);
        setMembersDialogOpen(true);
      }
    },
    [allTeams],
  );

  const handleEdit = useCallback(
    (teamId: string) => {
      const team = allTeams.find((t) => t.id === teamId);
      if (team) {
        setCreateFormOpen(false);
        setTeamToEdit(team);
      }
    },
    [allTeams],
  );

  const handleMembersSuccess = useCallback(async () => {
    try {
      await refetch();
    } catch (refreshErr) {
      console.error("Failed to refresh teams after member changes:", sanitizeError(refreshErr));
    }
  }, [refetch]);

  const handleDeleteConfirm = useCallback(async () => {
    if (!teamToDelete) return;

    const idToDelete = teamToDelete.id;
    const nameToDelete = teamToDelete.name;

    const previousTeams = allTeams;
    setAllTeams(allTeams.filter((t) => t.id !== idToDelete));
    setDeleteDialogOpen(false);
    setTeamToDelete(null);

    try {
      await deleteTeam(idToDelete);
      toast.success(intl.formatMessage({ id: "teams.delete.success" }, { name: nameToDelete }));

      try {
        await refetch();
      } catch (refreshErr) {
        console.error("Failed to refresh teams after deletion:", sanitizeError(refreshErr));
      }
    } catch (err) {
      setAllTeams(previousTeams);

      const errorMessage = sanitizeError(err);
      toast.error(intl.formatMessage({ id: "teams.delete.errorTitle" }), {
        description: errorMessage,
      });
      console.error("Failed to delete team:", errorMessage);
    }
  }, [allTeams, teamToDelete, intl, refetch]);

  const handleCreateSuccess = useCallback(async () => {
    toast.success(intl.formatMessage({ id: "teams.create.success" }));
    try {
      await refetch();
    } catch (refreshErr) {
      console.error("Failed to refresh teams after creation:", sanitizeError(refreshErr));
    }
  }, [intl, refetch]);

  const handleEditSuccess = useCallback(async () => {
    toast.success(intl.formatMessage({ id: "teams.edit.success" }));
    try {
      await refetch();
    } catch (refreshErr) {
      console.error("Failed to refresh teams after update:", sanitizeError(refreshErr));
    }
  }, [intl, refetch]);

  return (
    <div className="p-6">
      {createFormOpen || teamToEdit ? (
        <TeamForm
          isOpen={createFormOpen || teamToEdit != null}
          team={teamToEdit ?? undefined}
          onToggle={() => {
            setCreateFormOpen(false);
            setTeamToEdit(null);
          }}
          onSuccess={teamToEdit ? handleEditSuccess : handleCreateSuccess}
        />
      ) : isLoading ? (
        <div
          role="status"
          aria-live="polite"
          aria-busy="true"
          className="flex items-center justify-center p-12"
        >
          <span className="sr-only">{intl.formatMessage({ id: "teams.loading.sr" })}</span>
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-border border-t-primary" />
        </div>
      ) : (
        <>
          {error && (
            <div
              className="mb-6 rounded-lg border border-destructive/20 bg-destructive/10 p-4"
              role="alert"
              aria-live="assertive"
              aria-atomic="true"
            >
              <h3 className="mb-1 font-semibold">
                {intl.formatMessage({ id: "teams.error.loading" })}
              </h3>
              <p className="text-destructive">{error}</p>
            </div>
          )}

          {allTeams.length > 0 ? (
            <>
              <div className="flex justify-between items-center mb-6">
                <h1 className="text-base font-semibold text-foreground">
                  {intl.formatMessage({ id: "teams.all.title" })}
                </h1>
                <Button
                  variant="default"
                  className="h-7 rounded-sm px-4"
                  onClick={() => setCreateFormOpen(true)}
                >
                  <Plus className="h-4 w-4" />
                  {intl.formatMessage({ id: "teams.createTeam" })}
                </Button>
              </div>

              <TeamsTable
                teams={allTeams}
                isLoading={false}
                onEdit={handleEdit}
                onManageMembers={handleManageMembers}
                onDelete={handleDelete}
              />

              <div className="flex items-center justify-between mt-6">
                <div className="flex items-center gap-4">
                  <div className="text-sm text-gray-600 dark:text-gray-400">
                    {intl.formatMessage({ id: "teams.showing" }, { count: allTeams.length })}
                  </div>
                  <div className="flex items-center gap-2">
                    <label
                      htmlFor="limit-select"
                      className="text-sm text-gray-600 dark:text-gray-400"
                    >
                      {intl.formatMessage({ id: "teams.perPage" })}
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
                    aria-label={intl.formatMessage({ id: "teams.loadMore.aria" })}
                  >
                    {loadingMore
                      ? intl.formatMessage({ id: "teams.loadMore.loading" })
                      : intl.formatMessage({ id: "teams.loadMore" })}
                  </Button>
                )}
              </div>
            </>
          ) : (
            <div className="border border-border rounded-lg p-6 flex flex-col gap-2">
              <h2 className="text-base font-medium">
                {intl.formatMessage({ id: "teams.empty.title" })}
              </h2>
              <div className="py-5">
                <p className="text-sm text-foreground">
                  {intl.formatMessage({ id: "teams.empty.description" })}
                </p>
              </div>
              <Button
                className="bg-foreground text-background hover:bg-foreground/90 h-8 w-38 rounded-sm px-2 gap-1.5 text-sm font-medium"
                onClick={() => setCreateFormOpen(true)}
              >
                <Plus className="size-3" />
                {intl.formatMessage({ id: "teams.createTeam" })}
              </Button>
            </div>
          )}
        </>
      )}

      {teamToDelete && (
        <ConfirmDialog
          open={deleteDialogOpen}
          onOpenChange={setDeleteDialogOpen}
          title={intl.formatMessage({ id: "teams.delete.title" })}
          description={intl.formatMessage(
            { id: "teams.delete.description" },
            { name: teamToDelete.name },
          )}
          confirmLabel={intl.formatMessage({ id: "common.button.delete" })}
          cancelLabel={intl.formatMessage({ id: "common.button.cancel" })}
          variant="destructive"
          onConfirm={handleDeleteConfirm}
        />
      )}

      {teamForMembers && (
        <ManageTeamMembersDialog
          open={membersDialogOpen}
          onOpenChange={setMembersDialogOpen}
          teamId={teamForMembers.id}
          teamName={teamForMembers.name}
          onSuccess={handleMembersSuccess}
        />
      )}
    </div>
  );
}
