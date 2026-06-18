import { describe, it, expect, vi } from "vitest";
import { screen, render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nProvider } from "@/i18n";
import { VirtualServerDetailsDrawer } from "./VirtualServerDetailsDrawer";
import type { VirtualServer } from "@/types/server";

describe("VirtualServerDetailsDrawer", () => {
  const activeServer: VirtualServer = {
    id: "active-1",
    name: "Active Server",
    description: "Active server description",
    enabled: true,
    visibility: "team",
    version: "1.0.0",
    tags: ["tag1"],
    createdAt: "2024-01-01T00:00:00Z",
    updatedAt: "2024-01-02T00:00:00Z",
    associatedTools: ["tool1"],
    associatedToolIds: ["t1"],
  } as unknown as VirtualServer;

  const inactiveServer: VirtualServer = {
    id: "inactive-1",
    name: "Inactive Server",
    enabled: false,
    visibility: "private",
    tags: [],
    associatedTools: [],
  } as unknown as VirtualServer;

  const renderWithI18n = (ui: React.ReactElement) => {
    return render(<I18nProvider>{ui}</I18nProvider>);
  };

  it("renders loading state", () => {
    renderWithI18n(
      <VirtualServerDetailsDrawer
        server={activeServer}
        isLoading={true}
        error={null}
        onAddComponents={vi.fn()}
        onAddSources={vi.fn()}
        onOpenChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Loading server details...")).toBeInTheDocument();
  });

  it("renders error state", () => {
    renderWithI18n(
      <VirtualServerDetailsDrawer
        server={activeServer}
        isLoading={false}
        error={{ message: "Failed to load" }}
        onAddComponents={vi.fn()}
        onAddSources={vi.fn()}
        onOpenChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Failed to load");
  });

  it("renders active server details", () => {
    renderWithI18n(
      <VirtualServerDetailsDrawer
        server={activeServer}
        isLoading={false}
        error={null}
        onAddComponents={vi.fn()}
        onAddSources={vi.fn()}
        onOpenChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("heading", { name: "Active Server" })).toBeInTheDocument();
    expect(screen.getByText("Active server description")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("Team")).toBeInTheDocument();
    expect(screen.getByText("1.0.0")).toBeInTheDocument();
  });

  it("renders inactive server and fallback details", () => {
    renderWithI18n(
      <VirtualServerDetailsDrawer
        server={inactiveServer}
        isLoading={false}
        error={null}
        onAddComponents={vi.fn()}
        onAddSources={vi.fn()}
        onOpenChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("heading", { name: "Inactive Server" })).toBeInTheDocument();
    expect(screen.getByText("Inactive")).toBeInTheDocument();
    expect(screen.getByText("Private")).toBeInTheDocument();
    expect(screen.getByText("N/A")).toBeInTheDocument(); // version fallback
    expect(screen.getByText("No components found.")).toBeInTheDocument();
  });

  it("handles empty filtered components message", async () => {
    const user = userEvent.setup();
    renderWithI18n(
      <VirtualServerDetailsDrawer
        server={inactiveServer}
        isLoading={false}
        error={null}
        onAddComponents={vi.fn()}
        onAddSources={vi.fn()}
        onOpenChange={vi.fn()}
      />,
    );

    // Switch filter to tools
    const toolsFilterButton = screen.getByRole("button", { name: "Tools" });
    await user.click(toolsFilterButton);

    expect(screen.getByText("No tools found.")).toBeInTheDocument();
  });

  it("calls callback props", async () => {
    const user = userEvent.setup();
    const handleAddComponents = vi.fn();
    const handleAddSources = vi.fn();
    const handleOpenChange = vi.fn();

    renderWithI18n(
      <VirtualServerDetailsDrawer
        server={activeServer}
        isLoading={false}
        error={null}
        onAddComponents={handleAddComponents}
        onAddSources={handleAddSources}
        onOpenChange={handleOpenChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Add components" }));
    expect(handleAddComponents).toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Add sources" }));
    expect(handleAddSources).toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Close virtual server details" }));
    expect(handleOpenChange).toHaveBeenCalledWith(false);
  });
});
