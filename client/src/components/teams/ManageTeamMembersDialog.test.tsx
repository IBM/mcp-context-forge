import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { I18nProvider } from "@/i18n";
import { ManageTeamMembersDialog } from "./ManageTeamMembersDialog";
import type { MemberRow } from "@/hooks/useTeamMembersForm";

const hookState = {
  members: [] as MemberRow[],
  memberOptions: [] as { value: string; label: string }[],
  isLoading: false,
  isSaving: false,
  addRow: vi.fn(),
  removeRow: vi.fn(),
  changeEmail: vi.fn(),
  changeRole: vi.fn(),
  save: vi.fn(),
};

const mockCaptured: { options?: { onClose: () => void; onSuccess?: () => void } } = {};

vi.mock("@/hooks/useTeamMembersForm", () => ({
  AVAILABLE_ROLES: ["owner", "member"],
  useTeamMembersForm: (options: { onClose: () => void; onSuccess?: () => void }) => {
    mockCaptured.options = options;
    return hookState;
  },
}));

function renderDialog(ui: ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>);
}

function baseProps() {
  return {
    open: true,
    onOpenChange: vi.fn(),
    teamId: "team-1",
    teamName: "Engineering",
  };
}

function existingRow(overrides: Partial<MemberRow> = {}): MemberRow {
  return {
    id: "existing-0",
    email: "existing@example.com",
    role: "member",
    isExisting: true,
    ...overrides,
  };
}

function newRow(overrides: Partial<MemberRow> = {}): MemberRow {
  return {
    id: "new-1",
    email: "",
    role: "member",
    isExisting: false,
    ...overrides,
  };
}

describe("ManageTeamMembersDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hookState.members = [];
    hookState.memberOptions = [];
    hookState.isLoading = false;
    hookState.isSaving = false;
  });

  it("renders the title and description", () => {
    renderDialog(<ManageTeamMembersDialog {...baseProps()} />);

    expect(screen.getByText("Manage team members")).toBeInTheDocument();
    expect(
      screen.getByText("Add or remove team members and set their permission levels."),
    ).toBeInTheDocument();
  });

  it("shows a loading status while members are loading", () => {
    hookState.isLoading = true;
    renderDialog(<ManageTeamMembersDialog {...baseProps()} />);

    expect(screen.getByRole("status", { busy: true })).toBeInTheDocument();
  });

  it("renders column headers and a row per member", () => {
    hookState.members = [existingRow(), newRow()];
    renderDialog(<ManageTeamMembersDialog {...baseProps()} />);

    expect(screen.getByText("Name")).toBeInTheDocument();
    expect(screen.getByText("Role")).toBeInTheDocument();
    // One email combobox input per member row.
    expect(screen.getAllByPlaceholderText("Name or email...")).toHaveLength(2);
  });

  it("disables the email combobox for existing members", () => {
    hookState.members = [existingRow()];
    renderDialog(<ManageTeamMembersDialog {...baseProps()} />);

    // The email input for an existing member shows its email and is disabled.
    const emailInput = screen.getByPlaceholderText("Name or email...");
    expect(emailInput).toBeDisabled();
    expect(emailInput).toHaveValue("existing@example.com");
  });

  it("calls addRow when Add member is clicked", async () => {
    const user = userEvent.setup();
    renderDialog(<ManageTeamMembersDialog {...baseProps()} />);

    await user.click(screen.getByRole("button", { name: /Add member/i }));

    expect(hookState.addRow).toHaveBeenCalledTimes(1);
  });

  it("calls removeRow when a row's Remove button is clicked", async () => {
    const user = userEvent.setup();
    hookState.members = [existingRow()];
    renderDialog(<ManageTeamMembersDialog {...baseProps()} />);

    await user.click(screen.getByRole("button", { name: /Remove existing@example.com/i }));

    expect(hookState.removeRow).toHaveBeenCalledWith("existing-0");
  });

  it("calls save when Save is clicked", async () => {
    const user = userEvent.setup();
    renderDialog(<ManageTeamMembersDialog {...baseProps()} />);

    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(hookState.save).toHaveBeenCalledTimes(1);
  });

  it("closes the dialog when Cancel is clicked", async () => {
    const user = userEvent.setup();
    const props = baseProps();
    renderDialog(<ManageTeamMembersDialog {...props} />);

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(props.onOpenChange).toHaveBeenCalledWith(false);
  });

  it("shows the saving label and disables actions while saving", () => {
    hookState.isSaving = true;
    hookState.members = [existingRow()];
    renderDialog(<ManageTeamMembersDialog {...baseProps()} />);

    expect(screen.getByRole("button", { name: "Saving..." })).toBeDisabled();
    const removeButton = screen.getByRole("button", {
      name: /Remove existing@example.com/i,
    });
    expect(removeButton).toBeDisabled();
  });

  it("shows the current role on the row's role selector", () => {
    hookState.members = [newRow({ role: "owner" })];
    renderDialog(<ManageTeamMembersDialog {...baseProps()} />);

    // Two combobox-role controls: [0] the email Combobox, [1] the role Select trigger.
    const roleTrigger = screen.getAllByRole("combobox")[1];
    expect(roleTrigger).toHaveTextContent("owner");
  });

  it("closes the dialog via the onClose passed to the hook", () => {
    const props = baseProps();
    renderDialog(<ManageTeamMembersDialog {...props} />);

    mockCaptured.options?.onClose();

    expect(props.onOpenChange).toHaveBeenCalledWith(false);
  });

  it("calls changeEmail when an option is chosen in the email combobox", async () => {
    const user = userEvent.setup();
    hookState.members = [newRow({ id: "new-1" })];
    hookState.memberOptions = [
      { value: "picked@example.com", label: "Picked (picked@example.com)" },
    ];
    renderDialog(<ManageTeamMembersDialog {...baseProps()} />);

    await user.click(screen.getByPlaceholderText("Name or email..."));
    await user.click(await screen.findByText("Picked (picked@example.com)"));

    expect(hookState.changeEmail).toHaveBeenCalledWith("new-1", "picked@example.com");
  });

  it("calls changeRole when a new role is selected", async () => {
    const user = userEvent.setup();
    hookState.members = [newRow({ id: "new-1", role: "member" })];
    renderDialog(<ManageTeamMembersDialog {...baseProps()} />);

    await user.click(screen.getAllByRole("combobox")[1]);
    await user.click(await screen.findByRole("option", { name: "owner" }));

    expect(hookState.changeRole).toHaveBeenCalledWith("new-1", "owner");
  });
});
