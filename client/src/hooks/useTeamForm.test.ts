import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook as rtlRenderHook, act, waitFor } from "@testing-library/react";
import { createElement, type FormEvent, type ReactNode } from "react";
import { IntlProvider } from "react-intl";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { server } from "@/test/mocks/server";
import enMessages from "@/i18n/locales/en-US";
import type { Team } from "@/types/team";
import { useTeamForm } from "./useTeamForm";

const makeTeam = (overrides: Partial<Team> = {}): Team => ({
  id: "team-1",
  name: "Engineering",
  slug: "engineering",
  description: "Eng team",
  created_by: "admin@example.com",
  is_personal: false,
  visibility: "public",
  max_members: 50,
  member_count: 3,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  is_active: true,
  ...overrides,
});

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  },
}));

const mockToastWarning = vi.mocked(toast.warning);

const wrapper = ({ children }: { children: ReactNode }) =>
  createElement(
    IntlProvider,
    { locale: "en", defaultLocale: "en", messages: enMessages },
    children,
  );

const renderHook = <Result, Props>(render: (initialProps: Props) => Result) =>
  rtlRenderHook(render, { wrapper });

const fakeSubmit = (e?: Partial<FormEvent<HTMLFormElement>>) =>
  ({ preventDefault: vi.fn(), ...e }) as FormEvent<HTMLFormElement>;

beforeEach(() => {
  mockToastWarning.mockClear();
  // The hook loads the user directory on mount; keep it quiet by default.
  server.use(http.get("*/auth/email/admin/users", () => HttpResponse.json({ users: [] })));
});

describe("useTeamForm", () => {
  describe("Initial State", () => {
    it("initializes with defaults and a single owner member row", () => {
      const { result } = renderHook(() => useTeamForm());

      expect(result.current.name).toBe("");
      expect(result.current.description).toBe("");
      expect(result.current.visibility).toBe("private");
      expect(result.current.maxMembers).toBe("100");
      expect(result.current.members).toEqual([{ email: "", role: "owner" }]);
      expect(result.current.error).toBeNull();
      expect(result.current.isSubmitting).toBe(false);
    });
  });

  describe("member row actions", () => {
    it("adds, edits, and removes member rows", () => {
      const { result } = renderHook(() => useTeamForm());

      act(() => result.current.handleAddMember());
      expect(result.current.members).toHaveLength(2);

      act(() => {
        result.current.handleMemberEmailChange(1, "user@example.com");
        result.current.handleMemberRoleChange(1, "member");
      });
      expect(result.current.members[1]).toEqual({ email: "user@example.com", role: "member" });

      act(() => result.current.handleRemoveMember(0));
      expect(result.current.members).toEqual([{ email: "user@example.com", role: "member" }]);
    });
  });

  describe("validateForm", () => {
    it("returns false and sets an error when name is empty", () => {
      const { result } = renderHook(() => useTeamForm());

      let valid: boolean;
      act(() => {
        valid = result.current.validateForm();
      });

      expect(valid!).toBe(false);
      expect(result.current.error).toBeTruthy();
    });

    it("returns false when name contains disallowed characters", () => {
      const { result } = renderHook(() => useTeamForm());

      act(() => result.current.setName("bad/name"));

      let valid: boolean;
      act(() => {
        valid = result.current.validateForm();
      });

      expect(valid!).toBe(false);
      expect(result.current.error).toBeTruthy();
    });

    it("returns true for a valid name", () => {
      const { result } = renderHook(() => useTeamForm());

      act(() => result.current.setName("Engineering Team"));

      let valid: boolean;
      act(() => {
        valid = result.current.validateForm();
      });

      expect(valid!).toBe(true);
      expect(result.current.error).toBeNull();
    });
  });

  describe("handleSubmit", () => {
    it("does not call the API when the form is invalid", async () => {
      const postSpy = vi.fn(() => HttpResponse.json({}, { status: 201 }));
      server.use(http.post("*/teams", postSpy));

      const { result } = renderHook(() => useTeamForm());

      await act(async () => {
        await result.current.handleSubmit(fakeSubmit());
      });

      expect(postSpy).not.toHaveBeenCalled();
    });

    it("creates a team and calls onSuccess", async () => {
      let capturedBody: unknown;
      server.use(
        http.post("*/teams", async ({ request }) => {
          capturedBody = await request.json();
          return HttpResponse.json({ id: "team-1", name: "Engineering" }, { status: 201 });
        }),
      );

      const onSuccess = vi.fn();
      const { result } = renderHook(() => useTeamForm());

      act(() => result.current.setName("Engineering"));

      await act(async () => {
        await result.current.handleSubmit(fakeSubmit(), onSuccess);
      });

      await waitFor(() => expect(onSuccess).toHaveBeenCalledOnce());
      expect(capturedBody).toMatchObject({ name: "Engineering", visibility: "private" });
      // Form resets after a successful create.
      expect(result.current.name).toBe("");
    });

    it("adds filled members after creating the team", async () => {
      const memberBodies: unknown[] = [];
      server.use(
        http.post("*/teams", () =>
          HttpResponse.json({ id: "team-1", name: "Engineering" }, { status: 201 }),
        ),
        http.post("*/teams/team-1/members", async ({ request }) => {
          memberBodies.push(await request.json());
          return HttpResponse.json({}, { status: 201 });
        }),
      );

      const { result } = renderHook(() => useTeamForm());

      act(() => {
        result.current.setName("Engineering");
        result.current.handleMemberEmailChange(0, "owner@example.com");
      });

      await act(async () => {
        await result.current.handleSubmit(fakeSubmit());
      });

      await waitFor(() => expect(memberBodies).toHaveLength(1));
      expect(memberBodies[0]).toMatchObject({ email: "owner@example.com", role: "owner" });
    });

    it("closes the form and warns via toast when a member add fails", async () => {
      server.use(
        http.post("*/teams", () =>
          HttpResponse.json({ id: "team-1", name: "Engineering" }, { status: 201 }),
        ),
        http.post("*/teams/team-1/members", () =>
          HttpResponse.json({ detail: "User is already a member" }, { status: 409 }),
        ),
      );

      const onSuccess = vi.fn();
      const { result } = renderHook(() => useTeamForm());

      act(() => {
        result.current.setName("Engineering");
        result.current.handleMemberEmailChange(0, "owner@example.com");
      });

      await act(async () => {
        await result.current.handleSubmit(fakeSubmit(), onSuccess);
      });

      // The team already exists, so we proceed to success (form closes) but warn
      // about the members that could not be added.
      await waitFor(() => expect(onSuccess).toHaveBeenCalledOnce());
      expect(mockToastWarning).toHaveBeenCalledOnce();
      expect(mockToastWarning.mock.calls[0][1]).toMatchObject({
        description: expect.stringContaining("owner@example.com"),
      });
      expect(result.current.error).toBeNull();
      // Form resets after proceeding to success.
      expect(result.current.name).toBe("");
    });

    it("rejects an invalid member email before creating the team", async () => {
      const postSpy = vi.fn(() => HttpResponse.json({}, { status: 201 }));
      server.use(http.post("*/teams", postSpy));

      const onSuccess = vi.fn();
      const { result } = renderHook(() => useTeamForm());

      act(() => {
        result.current.setName("Engineering");
        result.current.handleMemberEmailChange(0, "not-an-email");
      });

      await act(async () => {
        await result.current.handleSubmit(fakeSubmit(), onSuccess);
      });

      expect(postSpy).not.toHaveBeenCalled();
      expect(onSuccess).not.toHaveBeenCalled();
      expect(result.current.error).toBeTruthy();
    });

    it("sets an error when team creation fails", async () => {
      server.use(
        http.post("*/teams", () =>
          HttpResponse.json({ detail: "Team already exists" }, { status: 409 }),
        ),
      );

      const onSuccess = vi.fn();
      const { result } = renderHook(() => useTeamForm());

      act(() => result.current.setName("Engineering"));

      await act(async () => {
        await result.current.handleSubmit(fakeSubmit(), onSuccess);
      });

      await waitFor(() => expect(result.current.error).toBeTruthy());
      expect(onSuccess).not.toHaveBeenCalled();
    });
  });

  describe("edit mode", () => {
    it("pre-populates state from the team and flags edit mode", () => {
      const team = makeTeam();
      const { result } = renderHook(() => useTeamForm(team));

      expect(result.current.isEditMode).toBe(true);
      expect(result.current.name).toBe("Engineering");
      expect(result.current.description).toBe("Eng team");
      expect(result.current.visibility).toBe("public");
      expect(result.current.maxMembers).toBe("50");
    });

    it("PUTs to the team endpoint and calls onSuccess without touching members", async () => {
      let capturedBody: unknown;
      const memberCalls: unknown[] = [];
      server.use(
        http.put("*/teams/team-1", async ({ request }) => {
          capturedBody = await request.json();
          return HttpResponse.json({ id: "team-1", name: "Renamed" });
        }),
        http.post("*/teams/team-1/members", async ({ request }) => {
          memberCalls.push(await request.json());
          return HttpResponse.json({}, { status: 201 });
        }),
      );

      const onSuccess = vi.fn();
      const { result } = renderHook(() => useTeamForm(makeTeam()));

      act(() => {
        result.current.setName("Renamed");
        result.current.setVisibility("private");
      });

      await act(async () => {
        await result.current.handleSubmit(fakeSubmit(), onSuccess);
      });

      await waitFor(() => expect(onSuccess).toHaveBeenCalledOnce());
      expect(capturedBody).toMatchObject({ name: "Renamed", visibility: "private" });
      // max_members was not touched, so it is omitted to preserve the team's value.
      expect(capturedBody).not.toHaveProperty("max_members");
      expect(memberCalls).toHaveLength(0);
      // Edit mode leaves the entered values in place (no reset to create defaults).
      expect(result.current.name).toBe("Renamed");
    });

    it("exposes an off-list max_members value as a selectable option", () => {
      const { result } = renderHook(() => useTeamForm(makeTeam({ max_members: 75 })));

      expect(result.current.maxMembers).toBe("75");
      // The custom value is merged into the presets in ascending order.
      expect(result.current.maxMembersOptions).toEqual([
        "10",
        "25",
        "50",
        "75",
        "100",
        "250",
        "500",
      ]);
    });

    it("keeps only the presets when max_members matches one", () => {
      const { result } = renderHook(() => useTeamForm(makeTeam({ max_members: 100 })));

      expect(result.current.maxMembersOptions).toEqual(["10", "25", "50", "100", "250", "500"]);
    });

    it("sends max_members only when the user changes it", async () => {
      let capturedBody: Record<string, unknown> = {};
      server.use(
        http.put("*/teams/team-1", async ({ request }) => {
          capturedBody = (await request.json()) as Record<string, unknown>;
          return HttpResponse.json({ id: "team-1", name: "Engineering" });
        }),
      );

      const { result } = renderHook(() => useTeamForm(makeTeam({ max_members: 50 })));

      act(() => result.current.setMaxMembers("250"));

      await act(async () => {
        await result.current.handleSubmit(fakeSubmit());
      });

      await waitFor(() => expect(capturedBody).toHaveProperty("max_members"));
      expect(capturedBody.max_members).toBe(250);
    });

    it("omits max_members for a team with no override so it stays unset", async () => {
      let capturedBody: Record<string, unknown> = {};
      server.use(
        http.put("*/teams/team-1", async ({ request }) => {
          capturedBody = (await request.json()) as Record<string, unknown>;
          return HttpResponse.json({ id: "team-1", name: "Engineering" });
        }),
      );

      // max_members undefined => the form shows the default ("100") but must not
      // pin the team to it on save.
      const { result } = renderHook(() => useTeamForm(makeTeam({ max_members: undefined })));

      act(() => result.current.setName("Engineering Renamed"));

      await act(async () => {
        await result.current.handleSubmit(fakeSubmit());
      });

      await waitFor(() => expect(capturedBody).toHaveProperty("name"));
      expect(capturedBody).not.toHaveProperty("max_members");
    });

    it("sets an error and skips onSuccess when the update fails", async () => {
      server.use(
        http.put("*/teams/team-1", () =>
          HttpResponse.json({ detail: "Update failed" }, { status: 403 }),
        ),
      );

      const onSuccess = vi.fn();
      const { result } = renderHook(() => useTeamForm(makeTeam()));

      await act(async () => {
        await result.current.handleSubmit(fakeSubmit(), onSuccess);
      });

      await waitFor(() => expect(result.current.error).toBeTruthy());
      expect(onSuccess).not.toHaveBeenCalled();
    });
  });
});
