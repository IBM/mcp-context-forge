import { describe, it, expect, vi } from "vitest";
import { screen, render, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AdvancedSettings } from "./AdvancedSettings";
import { AuthProvider } from "@/auth/AuthContext";

describe("AdvancedSettings", () => {
  const defaultProps = {
    visibility: "team",
    onVisibilityChange: vi.fn(),
    authType: "none" as any,
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
    oauthStoreTokens: true,
    oauthAutoRefresh: true,
    oauthUsername: "",
    oauthPassword: "", // pragma: allowlist secret
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
    queryParamApiKey: "", // pragma: allowlist secret
    onQueryParamNameChange: vi.fn(),
    onQueryParamApiKeyChange: vi.fn(),
    oneTimeAuth: false,
    onOneTimeAuthChange: vi.fn(),
    passthroughHeaders: "",
    onPassthroughHeadersChange: vi.fn(),
    onCACertificateFilesSelected: vi.fn(),
  };

  it("renders auth content according to authType", () => {
    const { rerender } = render(<AuthProvider><AdvancedSettings {...defaultProps} /></AuthProvider>);
    // "none" auth renders nothing special
    expect(screen.queryByLabelText(/Username/i)).not.toBeInTheDocument();

    // "basic" auth
    rerender(<AuthProvider><AdvancedSettings {...defaultProps} authType="basic" /></AuthProvider>);
    expect(screen.getByLabelText(/Username/i)).toBeInTheDocument();

    // "bearer" auth
    rerender(<AuthProvider><AdvancedSettings {...defaultProps} authType="bearer" /></AuthProvider>);
    expect(screen.getByPlaceholderText(/Paste bearer token/i)).toBeInTheDocument();

    // "custom" auth
    rerender(<AuthProvider><AdvancedSettings {...defaultProps} authType="custom" /></AuthProvider>);
    expect(screen.getByRole("button", { name: /\+?\s*Add header/i })).toBeInTheDocument();

    // "oauth" auth
    rerender(<AuthProvider><AdvancedSettings {...defaultProps} authType="oauth" /></AuthProvider>);
    expect(screen.getByLabelText(/Client ID/i)).toBeInTheDocument();

    // "query" auth
    rerender(<AuthProvider><AdvancedSettings {...defaultProps} authType="query" /></AuthProvider>);
    expect(screen.getByLabelText(/Parameter name/i)).toBeInTheDocument();

    // invalid/default authType
    rerender(<AuthProvider><AdvancedSettings {...defaultProps} authType={"invalid-type" as any} /></AuthProvider>);
    expect(screen.queryByLabelText(/Username/i)).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/Paste bearer token/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Parameter name/i)).not.toBeInTheDocument();
  });

  it("renders warning when oneTimeAuth is true", () => {
    const { rerender } = render(<AuthProvider><AdvancedSettings {...defaultProps} oneTimeAuth={false} /></AuthProvider>);
    expect(screen.queryByText(/Add passthrough headers when one-time/i)).not.toBeInTheDocument();

    rerender(<AuthProvider><AdvancedSettings {...defaultProps} oneTimeAuth={true} /></AuthProvider>);
    expect(screen.getByText(/Add passthrough headers when one-time/i)).toBeInTheDocument();
  });

  it("calls callback handlers when inputs change", async () => {
    const user = userEvent.setup();
    const handleAuthTypeChange = vi.fn();
    const handleOneTimeAuthChange = vi.fn();
    const handlePassthroughHeadersChange = vi.fn();

    render(
      <AuthProvider>
        <AdvancedSettings
          {...defaultProps}
          onAuthTypeChange={handleAuthTypeChange}
          onOneTimeAuthChange={handleOneTimeAuthChange}
          onPassthroughHeadersChange={handlePassthroughHeadersChange}
        />
      </AuthProvider>,
    );

    // Switch auth type
    const basicRadio = screen.getByLabelText("Basic");
    await user.click(basicRadio);
    expect(handleAuthTypeChange).toHaveBeenCalledWith("basic");

    // Toggle one time auth switch
    const oneTimeSwitch = screen.getByRole("switch", { name: /One-time authentication/i });
    await user.click(oneTimeSwitch);
    expect(handleOneTimeAuthChange).toHaveBeenCalled();

    // Change passthrough headers textarea
    const textarea = screen.getByLabelText("Passthrough headers");
    await user.type(textarea, "X-Custom-Header");
    expect(handlePassthroughHeadersChange).toHaveBeenCalled();
  });
});

