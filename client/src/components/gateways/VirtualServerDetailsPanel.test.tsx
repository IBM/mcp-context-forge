import { describe, it, expect, vi } from "vitest";
import { renderWithProviders } from "@/test/test-utils";
import { screen } from "@testing-library/react";
import { VirtualServerDetailsPanel } from "./VirtualServerDetailsPanel";
import type { VirtualServer } from "@/types/server";

// Mock the query hook
vi.mock("@/hooks/useQuery", () => ({
  useQuery: () => ({
    data: { gateways: [] },
    isLoading: false,
    error: null,
    fetchData: vi.fn(),
  }),
}));

const mockServer: VirtualServer = {
  id: "vs-1",
  name: "My Virtual Server",
  enabled: true,
  visibility: "team",
  oauthEnabled: true,
  tags: ["api", "test"],
  associatedTools: ["tool1", "tool2"],
  associatedResources: ["res1"],
  associatedPrompts: [],
  createdAt: "2024-01-01T00:00:00Z",
  updatedAt: "2024-06-01T00:00:00Z",
  description: "Test description",
};

describe("VirtualServerDetailsPanel", () => {
  it("renders server name and description", () => {
    renderWithProviders(
      <VirtualServerDetailsPanel
        server={mockServer}
        open={true}
        error={null}
        onClose={vi.fn()}
        onAddSources={vi.fn()}
      />
    );
    expect(screen.getByText("My Virtual Server")).toBeTruthy();
    expect(screen.getByText("Test description")).toBeTruthy();
  });

  it("renders configuration section", () => {
    renderWithProviders(
      <VirtualServerDetailsPanel
        server={mockServer}
        open={true}
        error={null}
        onClose={vi.fn()}
        onAddSources={vi.fn()}
      />
    );
    expect(screen.getByText("Virtual server details")).toBeTruthy();
  });

  it("renders the close button", () => {
    const onClose = vi.fn();
    renderWithProviders(
      <VirtualServerDetailsPanel
        server={mockServer}
        open={true}
        error={null}
        onClose={onClose}
        onAddSources={vi.fn()}
      />
    );
    const closeBtn = screen.getByRole("button", { name: /close/i });
    expect(closeBtn).toBeTruthy();
  });

  it("renders components list with tools and resources", () => {
    renderWithProviders(
      <VirtualServerDetailsPanel
        server={mockServer}
        open={true}
        error={null}
        onClose={vi.fn()}
        onAddSources={vi.fn()}
      />
    );
    // Should render the tools and resources listed in associatedTools/associatedResources
    expect(screen.getByText("tool1")).toBeTruthy();
    expect(screen.getByText("tool2")).toBeTruthy();
    expect(screen.getByText("res1")).toBeTruthy();
  });
});
