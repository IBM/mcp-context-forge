import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders as render } from "@/test/test-utils";
import { VirtualServerDetailsPanel } from "./VirtualServerDetailsPanel";
import type { VirtualServer } from "@/types/server";

function makeServer(overrides: Partial<VirtualServer> = {}): VirtualServer {
  return {
    id: "gateway-1",
    name: "GH repo tasks",
    description: "Test server",
    icon: "",
    createdAt: "2026-04-16T13:23:12Z",
    updatedAt: "2026-04-16T13:23:12Z",
    enabled: true,
    associatedTools: [],
    associatedToolIds: [],
    associatedResources: [],
    associatedPrompts: [],
    associatedA2aAgents: [],
    metrics: null,
    tags: [],
    createdBy: "admin@example.com",
    createdFromIp: "127.0.0.1",
    createdVia: "ui",
    createdUserAgent: "Mozilla/5.0",
    modifiedBy: null,
    modifiedFromIp: null,
    modifiedVia: null,
    modifiedUserAgent: null,
    importBatchId: null,
    federationSource: null,
    version: 1,
    teamId: "team-1",
    team: "Test Team",
    ownerEmail: "admin@example.com",
    visibility: "team",
    oauthEnabled: false,
    oauthConfig: null,
    ...overrides,
  };
}

describe("VirtualServerDetailsPanel inline tag add", () => {
  it("calls onAddTag with the merged, de-duplicated tag list", async () => {
    const user = userEvent.setup();
    const onAddTag = vi.fn().mockResolvedValue(undefined);

    render(
      <VirtualServerDetailsPanel
        server={makeServer({ id: "gw-1", tags: ["prod"] })}
        error={null}
        open
        onClose={vi.fn()}
        onAddSources={vi.fn()}
        onAddTag={onAddTag}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Add tags" }));
    await user.type(screen.getByPlaceholderText("Add tags separated with commas"), "staging, prod");
    await user.click(screen.getByRole("button", { name: "Add" }));

    // "prod" already exists and is dropped; "staging" is appended.
    expect(onAddTag).toHaveBeenCalledWith("gw-1", ["prod", "staging"]);
  });

  it("disables the add-tag trigger when onAddTag is omitted", () => {
    render(
      <VirtualServerDetailsPanel
        server={makeServer({ tags: [] })}
        error={null}
        open
        onClose={vi.fn()}
        onAddSources={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Add tags" })).toBeDisabled();
  });
});
