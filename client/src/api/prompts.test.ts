import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { buildCreatePromptPayload, createPrompt } from "./prompts";

vi.mock("./client", () => ({
  api: {
    post: vi.fn(),
  },
}));

describe("prompts API", () => {
  beforeEach(() => {
    vi.mocked(api.post).mockReset();
  });

  it("builds the create payload expected by POST /prompts", () => {
    expect(
      buildCreatePromptPayload({
        name: "Greeting prompt",
        visibility: "public",
        template: "Hello {{ name }}",
        arguments: '[{"name":"name","description":"Customer name","required":true}]',
        description: "Greets a customer",
        tags: "greeting, customer",
      }),
    ).toEqual({
      prompt: {
        name: "Greeting prompt",
        description: "Greets a customer",
        template: "Hello {{ name }}",
        arguments: [{ name: "name", description: "Customer name", required: true }],
        tags: ["greeting", "customer"],
        visibility: "public",
        team_id: null,
      },
      team_id: null,
      visibility: "public",
    });
  });

  it("includes the selected team id only for team-visible prompts", () => {
    expect(
      buildCreatePromptPayload({
        name: "Team prompt",
        visibility: "team",
        template: "Summarize {{ topic }}",
        arguments: "",
        teamId: "team-123",
      }),
    ).toMatchObject({
      prompt: {
        team_id: "team-123",
        visibility: "team",
      },
      team_id: "team-123",
      visibility: "team",
    });
  });

  it("creates prompts through the JSON prompts endpoint", async () => {
    vi.mocked(api.post).mockResolvedValue({
      id: "prompt-1",
      name: "Greeting prompt",
    });

    await createPrompt({
      name: "Greeting prompt",
      visibility: "public",
      template: "Hello",
      arguments: "",
    });

    expect(api.post).toHaveBeenCalledWith("/prompts", {
      prompt: {
        name: "Greeting prompt",
        description: undefined,
        template: "Hello",
        arguments: [],
        tags: undefined,
        visibility: "public",
        team_id: null,
      },
      team_id: null,
      visibility: "public",
    });
  });
});
