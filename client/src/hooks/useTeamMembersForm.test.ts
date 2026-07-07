import { describe, it, expect, beforeEach, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { I18nProvider } from "@/i18n";
import type { TeamMember } from "@/types/team";
import { useTeamMembersForm } from "./useTeamMembersForm";

vi.mock("@/api/teams", () => ({
  listTeamMembers: vi.fn(),
  addTeamMember: vi.fn(() => Promise.resolve()),
  updateTeamMember: vi.fn(() => Promise.resolve()),
  removeTeamMember: vi.fn(() => Promise.resolve()),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/api/client", () => ({
  api: { get: vi.fn(() => Promise.resolve({ users: [] })) },
}));

import { listTeamMembers, addTeamMember, updateTeamMember, removeTeamMember } from "@/api/teams";
import { api } from "@/api/client";
import { toast } from "sonner";

const TEAM_ID = "team-1";

function wrapper({ children }: { children: ReactNode }) {
  return createElement(I18nProvider, null, children);
}

function makeMember(overrides: Partial<TeamMember> = {}): TeamMember {
  return {
    user_email: "existing@example.com",
    role: "member",
    joined_at: "2024-01-01T00:00:00Z",
    invited_by: "owner@example.com",
    ...overrides,
  };
}

function renderForm(onSuccess = vi.fn(), onClose = vi.fn()) {
  return {
    onSuccess,
    onClose,
    ...renderHook(() => useTeamMembersForm({ open: true, teamId: TEAM_ID, onSuccess, onClose }), {
      wrapper,
    }),
  };
}

describe("useTeamMembersForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads members and hides those without an inviter", async () => {
    vi.mocked(listTeamMembers).mockResolvedValue([
      makeMember({ user_email: "a@example.com", invited_by: "owner@example.com" }),
      makeMember({ user_email: "b@example.com", invited_by: "" }),
      makeMember({ user_email: "c@example.com", invited_by: null }),
    ]);

    const { result } = renderForm();

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.members.map((m) => m.email)).toEqual(["a@example.com"]);
  });

  it("builds member options from the user directory", async () => {
    vi.mocked(listTeamMembers).mockResolvedValue([]);
    vi.mocked(api.get).mockResolvedValueOnce({
      users: [
        { email: "jane@example.com", full_name: "Jane Doe" },
        { email: "no-name@example.com", full_name: "" },
      ],
    });

    const { result } = renderForm();

    await waitFor(() => expect(result.current.memberOptions).toHaveLength(2));
    expect(result.current.memberOptions).toEqual([
      {
        value: "jane@example.com",
        label: "Jane Doe (jane@example.com)",
        searchText: "Jane Doe jane@example.com",
      },
      {
        value: "no-name@example.com",
        label: "no-name@example.com",
        searchText: "no-name@example.com",
      },
    ]);
  });

  it("fetches the full user directory with limit=0", async () => {
    vi.mocked(listTeamMembers).mockResolvedValue([]);
    renderForm();

    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith(
        "/auth/email/admin/users?limit=0&include_pagination=true",
      ),
    );
  });

  it("seeds one empty editable row when there are no members", async () => {
    vi.mocked(listTeamMembers).mockResolvedValue([]);
    const { result } = renderForm();

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.members).toHaveLength(1);
    expect(result.current.members[0]).toMatchObject({
      email: "",
      role: "member",
      isExisting: false,
    });
  });

  it("adds new members with an email on save", async () => {
    vi.mocked(listTeamMembers).mockResolvedValue([]);
    const { result, onSuccess, onClose } = renderForm();
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => result.current.addRow());
    const newId = result.current.members[0].id;
    act(() => result.current.changeEmail(newId, "new@example.com"));
    act(() => result.current.changeRole(newId, "owner"));

    await act(async () => {
      await result.current.save();
    });

    expect(addTeamMember).toHaveBeenCalledWith(TEAM_ID, {
      email: "new@example.com",
      role: "owner",
    });
    expect(onSuccess).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it("skips new rows with a blank email", async () => {
    vi.mocked(listTeamMembers).mockResolvedValue([]);
    const { result } = renderForm();
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => result.current.addRow());

    await act(async () => {
      await result.current.save();
    });

    expect(addTeamMember).not.toHaveBeenCalled();
  });

  it("updates the role of an existing member when it changes", async () => {
    vi.mocked(listTeamMembers).mockResolvedValue([
      makeMember({ user_email: "a@example.com", role: "member" }),
    ]);
    const { result } = renderForm();
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => result.current.changeRole(result.current.members[0].id, "owner"));

    await act(async () => {
      await result.current.save();
    });

    expect(updateTeamMember).toHaveBeenCalledWith(TEAM_ID, "a@example.com", {
      role: "owner",
    });
    expect(addTeamMember).not.toHaveBeenCalled();
    expect(removeTeamMember).not.toHaveBeenCalled();
  });

  it("does not update an existing member whose role is unchanged", async () => {
    vi.mocked(listTeamMembers).mockResolvedValue([
      makeMember({ user_email: "a@example.com", role: "member" }),
    ]);
    const { result } = renderForm();
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.save();
    });

    expect(updateTeamMember).not.toHaveBeenCalled();
  });

  it("removes existing members that were deleted from the rows", async () => {
    vi.mocked(listTeamMembers).mockResolvedValue([makeMember({ user_email: "a@example.com" })]);
    const { result } = renderForm();
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => result.current.removeRow(result.current.members[0].id));

    await act(async () => {
      await result.current.save();
    });

    expect(removeTeamMember).toHaveBeenCalledWith(TEAM_ID, "a@example.com");
  });

  it("uses the original email for existing members (email is immutable)", async () => {
    vi.mocked(listTeamMembers).mockResolvedValue([
      makeMember({ user_email: "a@example.com", role: "member" }),
    ]);
    const { result } = renderForm();
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    // Even if the row email were somehow changed, an existing member is only
    // ever role-updated by original email, never re-added under a new email.
    act(() => result.current.changeRole(result.current.members[0].id, "owner"));

    await act(async () => {
      await result.current.save();
    });

    expect(updateTeamMember).toHaveBeenCalledWith(TEAM_ID, "a@example.com", {
      role: "owner",
    });
    expect(addTeamMember).not.toHaveBeenCalled();
  });

  it("does not load members while the dialog is closed", () => {
    vi.mocked(listTeamMembers).mockResolvedValue([]);

    renderHook(
      () =>
        useTeamMembersForm({
          open: false,
          teamId: TEAM_ID,
          onSuccess: vi.fn(),
          onClose: vi.fn(),
        }),
      { wrapper },
    );

    expect(listTeamMembers).not.toHaveBeenCalled();
  });

  it("ignores the user directory response after unmount", async () => {
    vi.mocked(listTeamMembers).mockResolvedValue([]);
    let resolveUsers: (value: { users: unknown[] }) => void = () => {};
    vi.mocked(api.get).mockReturnValueOnce(
      new Promise((resolve) => {
        resolveUsers = resolve;
      }),
    );

    const { result, unmount } = renderForm();
    unmount();
    // Resolve the in-flight fetch only after the effect has been cleaned up.
    resolveUsers({ users: [{ email: "late@example.com", full_name: "Late" }] });
    await Promise.resolve();

    expect(result.current.memberOptions).toEqual([]);
  });

  it("logs an error when the user directory fetch fails", async () => {
    vi.mocked(listTeamMembers).mockResolvedValue([]);
    vi.mocked(api.get).mockRejectedValueOnce(new Error("no users"));
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const { result } = renderForm();

    await waitFor(() => expect(consoleSpy).toHaveBeenCalled());
    expect(result.current.memberOptions).toEqual([]);
    consoleSpy.mockRestore();
  });

  it("shows an error toast when loading members fails", async () => {
    vi.mocked(listTeamMembers).mockRejectedValue(new Error("forbidden"));

    const { result } = renderForm();

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(toast.error).toHaveBeenCalledWith(
      "Failed to load team members",
      expect.objectContaining({ description: expect.any(String) }),
    );
  });

  it("shows an error toast and stays open when saving fails", async () => {
    vi.mocked(listTeamMembers).mockResolvedValue([]);
    vi.mocked(addTeamMember).mockRejectedValueOnce(new Error("boom"));
    const { result, onClose } = renderForm();
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => result.current.changeEmail(result.current.members[0].id, "new@example.com"));

    await act(async () => {
      await result.current.save();
    });

    expect(toast.error).toHaveBeenCalledWith(
      "Failed to save team members",
      expect.objectContaining({ description: expect.any(String) }),
    );
    expect(onClose).not.toHaveBeenCalled();
  });
});
