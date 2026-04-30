import { useState } from "react";
import { ChevronsUpDown, Globe } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";
import { SidebarMenuButton } from "../ui/sidebar";
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

  const teams = data?.teams ?? [];
  const currentTeam = selectedTeam ? teams.find((t) => t.id === selectedTeam) : null;
  const displayName = currentTeam?.name ?? "All teams";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <SidebarMenuButton
          size="default"
          className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
        >
          <div className="flex aspect-square size-6 items-center justify-center">
            <Globe className="size-3 text-sidebar-foreground" />
          </div>
          <div className="grid flex-1 text-left text-sm leading-tight">
            <span className="truncate font-semibold">{isLoading ? "Loading..." : displayName}</span>
          </div>
          <ChevronsUpDown className="ml-auto" />
        </SidebarMenuButton>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        className="w-[--radix-dropdown-menu-trigger-width] min-w-56 rounded-lg"
        align="start"
        side="bottom"
        sideOffset={4}
      >
        {error && (
          <DropdownMenuItem disabled className="gap-2 p-2 text-destructive">
            Failed to load teams
          </DropdownMenuItem>
        )}
        {!error && teams.length === 0 && !isLoading && (
          <DropdownMenuItem disabled className="gap-2 p-2 text-muted-foreground">
            No teams available
          </DropdownMenuItem>
        )}
        <DropdownMenuItem className="gap-2 p-2" onClick={() => setSelectedTeam(null)}>
          <div className="flex size-6 items-center justify-center rounded-sm border bg-background">
            <Globe className="size-4 shrink-0 text-muted-foreground" />
          </div>
          All teams
        </DropdownMenuItem>
        {teams.map((team) => (
          <DropdownMenuItem
            key={team.id}
            className="gap-2 p-2"
            onClick={() => setSelectedTeam(team.id)}
          >
            <div className="flex size-6 items-center justify-center rounded-sm border bg-background">
              <Globe className="size-4 shrink-0 text-muted-foreground" />
            </div>
            {team.name}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
