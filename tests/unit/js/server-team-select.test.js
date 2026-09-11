import { describe, test, expect, beforeEach } from "vitest";
import {
  teamIdFromServer,
  setServerTeamSelect,
} from "../../../mcpgateway/admin_ui/servers.js";

describe("virtual server team select helpers", () => {
  beforeEach(() => {
    document.body.innerHTML =
      '<select id="edit-server-team-id">' +
      '<option value="">Select a team...</option>' +
      '<option value="team-a">Team A</option>' +
      '<option value="team-b">Team B</option>' +
      "</select>";
    window.USER_TEAMS_DATA = [
      { id: "team-a", name: "Team A" },
      { id: "team-b", name: "Team B" },
    ];
  });

  test("teamIdFromServer prefers camelCase teamId", () => {
    expect(teamIdFromServer({ teamId: "team-a", team_id: "team-b" })).toBe(
      "team-a"
    );
  });

  test("teamIdFromServer falls back to snake_case team_id", () => {
    expect(teamIdFromServer({ team_id: "team-b" })).toBe("team-b");
  });

  test("setServerTeamSelect applies preferred team id", () => {
    const applied = setServerTeamSelect("edit-server-team-id", "team-b");
    expect(applied).toBe("team-b");
    expect(document.getElementById("edit-server-team-id").value).toBe("team-b");
  });
});
