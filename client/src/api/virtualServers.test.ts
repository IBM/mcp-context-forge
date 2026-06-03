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

  it("includes associated tools when provided", () => {
    const payload = buildCreateVirtualServerPayload({
      name: "Tool server",
      visibility: "public",
      oauthEnabled: false,
      associatedTools: ["tool1", "tool2", "tool3"],
    });

    expect(payload).toMatchObject({
      server: {
        name: "Tool server",
        icon: "",
        tags: [],
        associated_tools: ["tool1", "tool2", "tool3"],
        associated_resources: [],
        associated_prompts: [],
        associated_a2a_agents: [],
        team_id: null,
        visibility: "public",
        oauth_enabled: false,
      },
      team_id: null,
      visibility: "public",
    });

    // description and oauth_config should not be present when undefined
    expect(payload.server.description).toBeUndefined();
    expect(payload.server.oauth_config).toBeUndefined();
  });

  it("includes associated resources when provided", () => {
    const payload = buildCreateVirtualServerPayload({
      name: "Resource server",
      visibility: "public",
      oauthEnabled: false,
      associatedResources: ["resource1", "resource2"],
    });

    expect(payload).toMatchObject({
      server: {
        name: "Resource server",
        icon: "",
        tags: [],
        associated_tools: [],
        associated_resources: ["resource1", "resource2"],
        associated_prompts: [],
        associated_a2a_agents: [],
        team_id: null,
        visibility: "public",
        oauth_enabled: false,
      },
      team_id: null,
      visibility: "public",
    });

    expect(payload.server.description).toBeUndefined();
    expect(payload.server.oauth_config).toBeUndefined();
  });

  it("includes associated prompts when provided", () => {
    const payload = buildCreateVirtualServerPayload({
      name: "Prompt server",
      visibility: "public",
      oauthEnabled: false,
      associatedPrompts: ["prompt1"],
    });

    expect(payload).toMatchObject({
      server: {
        name: "Prompt server",
        icon: "",
        tags: [],
        associated_tools: [],
        associated_resources: [],
        associated_prompts: ["prompt1"],
        associated_a2a_agents: [],
        team_id: null,
        visibility: "public",
        oauth_enabled: false,
      },
      team_id: null,
      visibility: "public",
    });

    expect(payload.server.description).toBeUndefined();
    expect(payload.server.oauth_config).toBeUndefined();
  });

  it("includes all associated components when provided", () => {
    expect(
      buildCreateVirtualServerPayload({
        name: "Full server",
        description: "Server with all components",
        visibility: "private",
        oauthEnabled: true,
        associatedTools: ["tool1", "tool2"],
        associatedResources: ["resource1"],
        associatedPrompts: ["prompt1", "prompt2", "prompt3"],
      }),
    ).toEqual({
      server: {
        name: "Full server",
        description: "Server with all components",
        icon: "",
        tags: [],
        associated_tools: ["tool1", "tool2"],
        associated_resources: ["resource1"],
        associated_prompts: ["prompt1", "prompt2", "prompt3"],
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

  it("defaults to empty arrays when associated components are undefined", () => {
    const payload = buildCreateVirtualServerPayload({
      name: "Minimal server",
      visibility: "public",
      oauthEnabled: false,
    });

    expect(payload).toMatchObject({
      server: {
        name: "Minimal server",
        icon: "",
        tags: [],
        associated_tools: [],
        associated_resources: [],
        associated_prompts: [],
        associated_a2a_agents: [],
        team_id: null,
        visibility: "public",
        oauth_enabled: false,
      },
      team_id: null,
      visibility: "public",
    });

    expect(payload.server.description).toBeUndefined();
    expect(payload.server.oauth_config).toBeUndefined();
  });

  it("sets team_id when visibility is team and teamId is provided", () => {
    const payload = buildCreateVirtualServerPayload({
      name: "Team server",
      visibility: "team",
      teamId: "team-abc-123",
      oauthEnabled: false,
    });

    expect(payload.server.team_id).toBe("team-abc-123");
    expect(payload.team_id).toBe("team-abc-123");
    expect(payload.visibility).toBe("team");
  });

  it("keeps team_id null when visibility is team but teamId is absent", () => {
    const payload = buildCreateVirtualServerPayload({
      name: "Team server no id",
      visibility: "team",
      oauthEnabled: false,
    });

    expect(payload.server.team_id).toBeNull();
    expect(payload.team_id).toBeNull();
  });

  it("keeps team_id null when teamId is provided but visibility is not team", () => {
    const payload = buildCreateVirtualServerPayload({
      name: "Private server",
      visibility: "private",
      teamId: "team-abc-123",
      oauthEnabled: false,
    });

    expect(payload.server.team_id).toBeNull();
    expect(payload.team_id).toBeNull();
  });
});
