import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as AuthContextModule from "@/auth/AuthContext";
import { AdvancedSettings } from "./AdvancedSettings";

vi.mock("@/auth/AuthContext", () => ({
  useAuthContext: vi.fn(),
}));

const mockUseAuthContext = vi.mocked(AuthContextModule.useAuthContext);

type AdvancedSettingsProps = Parameters<typeof AdvancedSettings>[0];

const makeAuthContext = (selectedTeamId: string | null = null) =>
  ({
    selectedTeamId,
    user: null,
    isAuthenticated: false,
    isLoading: false,
    login: vi.fn(),
    logout: vi.fn(),
    setSelectedTeamId: vi.fn(),
  }) as ReturnType<typeof AuthContextModule.useAuthContext>;

const makeProps = (overrides: Partial<AdvancedSettingsProps> = {}): AdvancedSettingsProps => ({
  visibility: "public",
  onVisibilityChange: vi.fn(),
  teamId: "",
  onTeamIdChange: vi.fn(),
  authType: "none",
  onAuthTypeChange: vi.fn(),
  basicAuthUsername: "",
  basicAuthPassword: "",
  onBasicAuthUsernameChange: vi.fn(),
  onBasicAuthPasswordChange: vi.fn(),
  bearerToken: "",
  onBearerTokenChange: vi.fn(),
  customHeaders: [],
  onCustomHeadersChange: vi.fn(),
  oauthClientId: "",
  oauthClientSecret: "",
  oauthTokenUrl: "",
  oauthGrantType: "client_credentials",
  oauthIssuerUrl: "",
  oauthRedirectUri: "",
  oauthAuthorizationUrl: "",
  oauthScopes: "",
  oauthStoreTokens: false,
  oauthAutoRefresh: false,
  oauthUsername: "",
  oauthPassword: "",
  onOAuthClientIdChange: vi.fn(),
  onOAuthClientSecretChange: vi.fn(),
  onOAuthTokenUrlChange: vi.fn(),
  onOAuthGrantTypeChange: vi.fn(),
  onOAuthIssuerUrlChange: vi.fn(),
  onOAuthRedirectUriChange: vi.fn(),
  onOAuthAuthorizationUrlChange: vi.fn(),
  onOAuthScopesChange: vi.fn(),
  onOAuthStoreTokensChange: vi.fn(),
  onOAuthAutoRefreshChange: vi.fn(),
  onOAuthUsernameChange: vi.fn(),
  onOAuthPasswordChange: vi.fn(),
  queryParamName: "",
  queryParamApiKey: "",
  onQueryParamNameChange: vi.fn(),
  onQueryParamApiKeyChange: vi.fn(),
  oneTimeAuth: false,
  onOneTimeAuthChange: vi.fn(),
  passthroughHeaders: "",
  onPassthroughHeadersChange: vi.fn(),
  onCACertificateFilesSelected: vi.fn(),
  ...overrides,
});

describe("AdvancedSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseAuthContext.mockReturnValue(makeAuthContext());
  });

  describe("team visibility — teamId sync (issue #5077)", () => {
    it("syncs teamId with selectedTeamId on mount when visibility is team and teamId is unset", () => {
      mockUseAuthContext.mockReturnValue(makeAuthContext("team-A"));
      const onTeamIdChange = vi.fn();

      render(
        <AdvancedSettings {...makeProps({ visibility: "team", teamId: "", onTeamIdChange })} />,
      );

      expect(onTeamIdChange).toHaveBeenCalledWith("team-A");
    });

    it("propagates selectedTeamId change after teamId is already set (regression: was ignored by !teamId guard)", () => {
      mockUseAuthContext.mockReturnValue(makeAuthContext("team-A"));
      const onTeamIdChange = vi.fn();
      const { rerender } = render(
        <AdvancedSettings
          {...makeProps({ visibility: "team", teamId: "team-A", onTeamIdChange })}
        />,
      );
      onTeamIdChange.mockClear();

      // User switches the sidebar team switcher to team-B before submitting
      mockUseAuthContext.mockReturnValue(makeAuthContext("team-B"));
      rerender(
        <AdvancedSettings
          {...makeProps({ visibility: "team", teamId: "team-A", onTeamIdChange })}
        />,
      );

      expect(onTeamIdChange).toHaveBeenCalledWith("team-B");
    });

    it("does not call onTeamIdChange when selectedTeamId already matches teamId", () => {
      mockUseAuthContext.mockReturnValue(makeAuthContext("team-A"));
      const onTeamIdChange = vi.fn();

      render(
        <AdvancedSettings
          {...makeProps({ visibility: "team", teamId: "team-A", onTeamIdChange })}
        />,
      );

      expect(onTeamIdChange).not.toHaveBeenCalled();
    });

    it("clears teamId when visibility changes away from team", () => {
      mockUseAuthContext.mockReturnValue(makeAuthContext("team-A"));
      const onTeamIdChange = vi.fn();
      const { rerender } = render(
        <AdvancedSettings
          {...makeProps({ visibility: "team", teamId: "team-A", onTeamIdChange })}
        />,
      );
      onTeamIdChange.mockClear();

      rerender(
        <AdvancedSettings
          {...makeProps({ visibility: "public", teamId: "team-A", onTeamIdChange })}
        />,
      );

      expect(onTeamIdChange).toHaveBeenCalledWith("");
    });

    it("clears teamId when selectedTeamId becomes null while visibility is team", () => {
      mockUseAuthContext.mockReturnValue(makeAuthContext(null));
      const onTeamIdChange = vi.fn();

      render(
        <AdvancedSettings
          {...makeProps({ visibility: "team", teamId: "team-A", onTeamIdChange })}
        />,
      );

      expect(onTeamIdChange).toHaveBeenCalledWith("");
    });

    it("does not call onTeamIdChange when visibility is not team and teamId is already empty", () => {
      mockUseAuthContext.mockReturnValue(makeAuthContext("team-A"));
      const onTeamIdChange = vi.fn();

      render(
        <AdvancedSettings {...makeProps({ visibility: "public", teamId: "", onTeamIdChange })} />,
      );

      expect(onTeamIdChange).not.toHaveBeenCalled();
    });

    it("tracks each subsequent sidebar team switch while visibility stays team", () => {
      mockUseAuthContext.mockReturnValue(makeAuthContext("team-A"));
      const onTeamIdChange = vi.fn();
      const { rerender } = render(
        <AdvancedSettings
          {...makeProps({ visibility: "team", teamId: "team-A", onTeamIdChange })}
        />,
      );
      onTeamIdChange.mockClear();

      mockUseAuthContext.mockReturnValue(makeAuthContext("team-B"));
      rerender(
        <AdvancedSettings
          {...makeProps({ visibility: "team", teamId: "team-A", onTeamIdChange })}
        />,
      );
      expect(onTeamIdChange).toHaveBeenCalledWith("team-B");
      onTeamIdChange.mockClear();

      mockUseAuthContext.mockReturnValue(makeAuthContext("team-C"));
      rerender(
        <AdvancedSettings
          {...makeProps({ visibility: "team", teamId: "team-B", onTeamIdChange })}
        />,
      );
      expect(onTeamIdChange).toHaveBeenCalledWith("team-C");
    });
  });

  describe("team visibility — hint message", () => {
    it("shows 'scoped to currently selected team' when visibility is team and a team is selected", () => {
      mockUseAuthContext.mockReturnValue(makeAuthContext("team-A"));

      render(<AdvancedSettings {...makeProps({ visibility: "team", teamId: "team-A" })} />);

      expect(screen.getByText(/scoped to your currently selected team/i)).toBeInTheDocument();
    });

    it("shows 'please select a team' when visibility is team but no team is selected", () => {
      mockUseAuthContext.mockReturnValue(makeAuthContext(null));

      render(<AdvancedSettings {...makeProps({ visibility: "team", teamId: "" })} />);

      expect(screen.getByText(/please select a team using the team switcher/i)).toBeInTheDocument();
    });

    it("does not show either team hint when visibility is not team", () => {
      mockUseAuthContext.mockReturnValue(makeAuthContext("team-A"));

      render(<AdvancedSettings {...makeProps({ visibility: "public" })} />);

      expect(screen.queryByText(/scoped to your currently selected team/i)).not.toBeInTheDocument();
      expect(
        screen.queryByText(/please select a team using the team switcher/i),
      ).not.toBeInTheDocument();
    });
  });

  describe("authentication settings", () => {
    it("renders auth content according to authType", () => {
      const { rerender } = render(<AdvancedSettings {...makeProps()} />);

      expect(screen.queryByLabelText(/Username/i)).not.toBeInTheDocument();

      rerender(<AdvancedSettings {...makeProps({ authType: "basic" })} />);
      expect(screen.getByLabelText(/Username/i)).toBeInTheDocument();

      rerender(<AdvancedSettings {...makeProps({ authType: "bearer" })} />);
      expect(screen.getByPlaceholderText(/Paste bearer token/i)).toBeInTheDocument();

      rerender(<AdvancedSettings {...makeProps({ authType: "custom" })} />);
      expect(screen.getByRole("button", { name: /\+?\s*Add header/i })).toBeInTheDocument();

      rerender(<AdvancedSettings {...makeProps({ authType: "oauth" })} />);
      expect(screen.getByLabelText(/Client ID/i)).toBeInTheDocument();

      rerender(<AdvancedSettings {...makeProps({ authType: "query" })} />);
      expect(screen.getByLabelText(/Parameter name/i)).toBeInTheDocument();

      rerender(<AdvancedSettings {...makeProps({ authType: "invalid-type" as never })} />);
      expect(screen.queryByLabelText(/Username/i)).not.toBeInTheDocument();
      expect(screen.queryByPlaceholderText(/Paste bearer token/i)).not.toBeInTheDocument();
      expect(screen.queryByLabelText(/Parameter name/i)).not.toBeInTheDocument();
    });

    it("renders warning when oneTimeAuth is true", () => {
      const { rerender } = render(<AdvancedSettings {...makeProps({ oneTimeAuth: false })} />);
      expect(screen.queryByText(/Add passthrough headers when one-time/i)).not.toBeInTheDocument();

      rerender(<AdvancedSettings {...makeProps({ oneTimeAuth: true })} />);
      expect(screen.getByText(/Add passthrough headers when one-time/i)).toBeInTheDocument();
    });

    it("calls callback handlers when inputs change", async () => {
      const user = userEvent.setup();
      const handleAuthTypeChange = vi.fn();
      const handleOneTimeAuthChange = vi.fn();
      const handlePassthroughHeadersChange = vi.fn();

      render(
        <AdvancedSettings
          {...makeProps({
            onAuthTypeChange: handleAuthTypeChange,
            onOneTimeAuthChange: handleOneTimeAuthChange,
            onPassthroughHeadersChange: handlePassthroughHeadersChange,
          })}
        />,
      );

      await user.click(screen.getByLabelText("Basic"));
      expect(handleAuthTypeChange).toHaveBeenCalledWith("basic");

      await user.click(screen.getByRole("switch", { name: /One-time authentication/i }));
      expect(handleOneTimeAuthChange).toHaveBeenCalled();

      await user.type(screen.getByLabelText("Passthrough headers"), "X-Custom-Header");
      expect(handlePassthroughHeadersChange).toHaveBeenCalled();
    });
  });
});
