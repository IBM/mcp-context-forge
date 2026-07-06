import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook as rtlRenderHook, act, waitFor } from "@testing-library/react";
import { createElement, type FormEvent, type ReactNode } from "react";
import { IntlProvider } from "react-intl";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { server } from "@/test/mocks/server";
import enMessages from "@/i18n/locales/en-US";
import { useTeamForm } from "./useTeamForm";

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
});
