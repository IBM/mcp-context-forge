import { useState, useMemo, useCallback } from "react";
import { ChevronsUpDown, Globe } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";
import { useQuery } from "../../hooks/useQuery";

interface Team {
  id: string;
  name: string;
  description?: string;
}

interface TeamsResponse {
  teams: Team[];
}

export function TeamSwitcher() {
  const [selectedTeam, setSelectedTeam] = useState<string | null>(null);
  const { data, isLoading, error } = useQuery<TeamsResponse>("/teams");

  const teams = useMemo(() => data?.teams ?? [], [data?.teams]);
  const currentTeam = useMemo(
    () => (selectedTeam ? teams.find((t) => t.id === selectedTeam) : null),
    [selectedTeam, teams],
  );
  const displayName = currentTeam?.name ?? "All teams";

  const handleSelectTeam = useCallback((teamId: string | null) => {
    setSelectedTeam(teamId);
  }, []);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="inline-flex h-8 items-center gap-2 rounded-lg px-2 text-sm font-medium text-foreground transition-colors hover:bg-muted"
          aria-label={`Select team. Current: ${displayName}`}
          aria-haspopup="menu"
          aria-expanded={undefined}
        >
          <Globe className="size-4 text-muted-foreground" aria-hidden="true" />
          <span className="max-w-40 truncate" aria-live={isLoading ? "polite" : "off"}>
            {isLoading ? "Loading..." : displayName}
          </span>
          <ChevronsUpDown className="size-4 text-muted-foreground" aria-hidden="true" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        className="min-w-56 rounded-lg w-56"
        align="start"
        side="bottom"
        sideOffset={4}
      >
        {error ? (
          <DropdownMenuItem disabled className="gap-2 p-2 text-destructive" role="alert">
            Failed to load teams
          </DropdownMenuItem>
        ) : null}
        {!error && teams.length === 0 && !isLoading && (
          <DropdownMenuItem disabled className="gap-2 p-2 text-muted-foreground" role="status">
            No teams available
          </DropdownMenuItem>
        )}
        <DropdownMenuItem
          className="gap-2 p-2"
          onClick={() => handleSelectTeam(null)}
          aria-label="Select all teams"
          aria-current={selectedTeam === null ? "true" : "false"}
        >
          <div
            className="flex size-6 items-center justify-center rounded-sm border bg-background"
            aria-hidden="true"
          >
            <Globe className="size-4 shrink-0 text-muted-foreground" />
          </div>
          All teams
        </DropdownMenuItem>
        {teams.map((team) => (
          <DropdownMenuItem
            key={team.id}
            className="gap-2 p-2"
            onClick={() => handleSelectTeam(team.id)}
            aria-label={`Select ${team.name} team${team.description ? `: ${team.description}` : ""}`}
            aria-current={selectedTeam === team.id ? "true" : "false"}
          >
            <div
              className="flex size-6 items-center justify-center rounded-sm border bg-background"
              aria-hidden="true"
            >
              <Globe className="size-4 shrink-0 text-muted-foreground" />
            </div>
            {team.name}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
