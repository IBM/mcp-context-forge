import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { TeamsTable } from "./TeamsTable";
import { I18nProvider } from "@/i18n";
import type { Team } from "../../types/team";

function renderTable(ui: ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>);
}

function makeTeam(overrides: Partial<Team> = {}): Team {
  return {
    id: "team-1",
    name: "Engineering",
    slug: "engineering",
    description: "The engineering team",
    created_by: "owner@example.com",
    is_personal: false,
    visibility: "private",
    max_members: 50,
    member_count: 7,
    created_at: "2024-01-01T08:30:00Z",
    updated_at: "2024-02-15T12:45:30Z",
    is_active: true,
    ...overrides,
  };
}

describe("TeamsTable", () => {
  it("renders the loading state when isLoading is true", () => {
    renderTable(<TeamsTable teams={[]} isLoading={true} />);

    const status = screen.getByRole("status", { busy: true });
    expect(status).toBeInTheDocument();
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(screen.getByText(/Loading teams, please wait/i)).toBeInTheDocument();
  });

  it("renders the column headers", () => {
    renderTable(<TeamsTable teams={[makeTeam()]} isLoading={false} />);

    expect(screen.getByRole("columnheader", { name: "Name" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Visibility" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Members" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Created" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Updated" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Actions" })).toBeInTheDocument();
  });

  it("renders a row for each team with its details", () => {
    const teams = [
      makeTeam({ id: "a", name: "Alpha", visibility: "public", member_count: 3 }),
      makeTeam({ id: "b", name: "Beta", visibility: "private", member_count: 12 }),
    ];

    renderTable(<TeamsTable teams={teams} isLoading={false} />);

    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("public")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();

    expect(screen.getByText("Beta")).toBeInTheDocument();
    expect(screen.getByText("private")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
  });

  it("renders the uppercase first-letter icon for a team", () => {
    renderTable(<TeamsTable teams={[makeTeam({ name: "engineering" })]} isLoading={false} />);

    expect(screen.getByText("E")).toBeInTheDocument();
  });

  it("formats valid created/updated dates", () => {
    renderTable(
      <TeamsTable
        teams={[
          makeTeam({
            created_at: "2024-01-01T08:30:00Z",
            updated_at: "2024-02-15T12:45:30Z",
          }),
        ]}
        isLoading={false}
      />,
    );

    // Formatted as YYYY-MM-DDTHH:mm:ss in the sv-SE locale.
    expect(screen.getByText(/^2024-01-01T/)).toBeInTheDocument();
    expect(screen.getByText(/^2024-02-15T/)).toBeInTheDocument();
  });

  it("renders 'Invalid date' for an unparseable date", () => {
    renderTable(<TeamsTable teams={[makeTeam({ created_at: "not-a-date" })]} isLoading={false} />);

    expect(screen.getByText("Invalid date")).toBeInTheDocument();
  });

  it("always renders Edit/Delete items, even when no handlers are provided", async () => {
    const user = userEvent.setup();
    renderTable(<TeamsTable teams={[makeTeam({ name: "Alpha" })]} isLoading={false} />);

    await user.click(screen.getByRole("button", { name: /Actions for Alpha/i }));

    expect(await screen.findByRole("menuitem", { name: /Edit/i })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /Delete/i })).toBeInTheDocument();
  });

  it("clicking Edit/Delete without handlers is a no-op and does not crash", async () => {
    const user = userEvent.setup();
    renderTable(<TeamsTable teams={[makeTeam({ name: "Alpha" })]} isLoading={false} />);

    await user.click(screen.getByRole("button", { name: /Actions for Alpha/i }));
    await user.click(await screen.findByRole("menuitem", { name: /Edit/i }));

    // Menu closes after selection; reopen and exercise Delete too.
    await user.click(screen.getByRole("button", { name: /Actions for Alpha/i }));
    await user.click(await screen.findByRole("menuitem", { name: /Delete/i }));

    expect(screen.getByText("Alpha")).toBeInTheDocument();
  });

  it("calls onEdit with the team id when Edit is clicked", async () => {
    const user = userEvent.setup();
    const onEdit = vi.fn();
    renderTable(
      <TeamsTable
        teams={[makeTeam({ id: "team-42", name: "Alpha" })]}
        isLoading={false}
        onEdit={onEdit}
      />,
    );

    await user.click(screen.getByRole("button", { name: /Actions for Alpha/i }));
    await user.click(await screen.findByRole("menuitem", { name: /Edit/i }));

    expect(onEdit).toHaveBeenCalledWith("team-42");
  });

  it("calls onDelete with the team id when Delete is clicked", async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn();
    renderTable(
      <TeamsTable
        teams={[makeTeam({ id: "team-99", name: "Alpha" })]}
        isLoading={false}
        onDelete={onDelete}
      />,
    );

    await user.click(screen.getByRole("button", { name: /Actions for Alpha/i }));
    await user.click(await screen.findByRole("menuitem", { name: /Delete/i }));

    expect(onDelete).toHaveBeenCalledWith("team-99");
  });

  it("renders an accessible actions trigger per team", () => {
    const teams = [makeTeam({ id: "a", name: "Alpha" }), makeTeam({ id: "b", name: "Beta" })];
    renderTable(<TeamsTable teams={teams} isLoading={false} />);

    expect(screen.getByRole("button", { name: "Actions for Alpha" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Actions for Beta" })).toBeInTheDocument();
  });

  it("renders an empty body without rows when there are no teams", () => {
    renderTable(<TeamsTable teams={[]} isLoading={false} />);

    // Header row only, no team data rows.
    expect(screen.getByRole("columnheader", { name: "Name" })).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).queryByRole("button", { name: /Actions for/i })).not.toBeInTheDocument();
  });

  it("shows a description trigger when the team has a description", () => {
    renderTable(
      <TeamsTable
        teams={[makeTeam({ name: "Alpha", description: "All org team for automation." })]}
        isLoading={false}
      />,
    );

    expect(screen.getByRole("button", { name: "View description for Alpha" })).toBeInTheDocument();
  });

  it("does not show a description trigger when the team has no description", () => {
    renderTable(
      <TeamsTable
        teams={[makeTeam({ name: "Alpha", description: undefined })]}
        isLoading={false}
      />,
    );

    expect(
      screen.queryByRole("button", { name: "View description for Alpha" }),
    ).not.toBeInTheDocument();
  });

  it("reveals the description in a popover when the trigger is clicked", async () => {
    const user = userEvent.setup();
    renderTable(
      <TeamsTable
        teams={[makeTeam({ name: "Alpha", description: "All org team for automation." })]}
        isLoading={false}
      />,
    );

    expect(screen.queryByText("All org team for automation.")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "View description for Alpha" }));

    expect(await screen.findByText("All org team for automation.")).toBeInTheDocument();
  });
});
