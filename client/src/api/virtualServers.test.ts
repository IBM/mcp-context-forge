import { describe, expect, it } from "vitest";
import { buildCreateVirtualServerPayload } from "./virtualServers";

describe("virtualServers API", () => {
  it("builds the create payload expected by POST /servers", () => {
    expect(
      buildCreateVirtualServerPayload({
        name: "Research server",
        description: "A composed endpoint for research tools.",
        tags: ["research", "tools"],
        visibility: "private",
        oauthEnabled: true,
      }),
    ).toEqual({
      server: {
        name: "Research server",
        description: "A composed endpoint for research tools.",
        icon: "",
        tags: ["research", "tools"],
        associated_tools: [],
        associated_resources: [],
        associated_prompts: [],
        associated_a2a_agents: [],
        team_id: null,
        visibility: "private",
        oauth_enabled: true,
        oauth_config: {},
      },
      team_id: null,
      visibility: "private",
    });
  });
});
