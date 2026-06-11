import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";
import { OAuth2Auth } from "./OAuth2Auth";

describe("OAuth2Auth", () => {
  const defaultProps = {
    grantType: "client_credentials",
    issuerUrl: "",
    redirectUri: "",
    clientId: "",
    clientSecret: "", // pragma: allowlist secret
    tokenUrl: "",
    authorizationUrl: "",
    scopes: "",
    storeTokens: true,
    autoRefresh: true,
    username: "",
    password: "", // pragma: allowlist secret
    onGrantTypeChange: vi.fn(),
    onIssuerUrlChange: vi.fn(),
    onRedirectUriChange: vi.fn(),
    onClientIdChange: vi.fn(),
    onClientSecretChange: vi.fn(),
    onTokenUrlChange: vi.fn(),
    onAuthorizationUrlChange: vi.fn(),
    onScopesChange: vi.fn(),
    onStoreTokensChange: vi.fn(),
    onAutoRefreshChange: vi.fn(),
    onUsernameChange: vi.fn(),
    onPasswordChange: vi.fn(),
  };

  it("should render client_credentials fields by default", () => {
    render(<OAuth2Auth {...defaultProps} />);

    expect(screen.getByLabelText(/Grant type/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Issuer URL/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Client ID/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Client Secret/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Token URL/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Scopes/i)).toBeInTheDocument();

    // Checkboxes
    expect(screen.getByLabelText(/Store access tokens for reuse/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Automatically refresh expired tokens/i)).toBeInTheDocument();

    // Fields that should NOT be visible for client_credentials
    expect(screen.queryByLabelText(/Redirect URI/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Authorization URL/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Username/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Password/i)).not.toBeInTheDocument();
  });

  it("should render authorization_code fields", () => {
    render(<OAuth2Auth {...defaultProps} grantType="authorization_code" />);

    expect(screen.getByLabelText(/Redirect URI/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Authorization URL/i)).toBeInTheDocument();

    expect(screen.queryByLabelText(/Username/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Password/i)).not.toBeInTheDocument();
  });

  it("should render password fields", () => {
    render(<OAuth2Auth {...defaultProps} grantType="password" />);

    expect(screen.getByLabelText(/Username/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Password/i)).toBeInTheDocument();

    expect(screen.queryByLabelText(/Redirect URI/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Authorization URL/i)).not.toBeInTheDocument();
  });

  it("should display errors for username and password in password grant", () => {
    render(
      <OAuth2Auth
        {...defaultProps}
        grantType="password"
        errors={{ username: "Username is required", password: "Password is required" }} // pragma: allowlist secret
      />,
    );

    expect(screen.getByText("Username is required")).toBeInTheDocument();
    expect(screen.getByText("Password is required")).toBeInTheDocument();
  });

  it("should trigger callbacks when fields are updated", () => {
    const onIssuerUrlChange = vi.fn();
    const onClientIdChange = vi.fn();
    const onClientSecretChange = vi.fn();
    const onTokenUrlChange = vi.fn();
    const onScopesChange = vi.fn();

    render(
      <OAuth2Auth
        {...defaultProps}
        onIssuerUrlChange={onIssuerUrlChange}
        onClientIdChange={onClientIdChange}
        onClientSecretChange={onClientSecretChange}
        onTokenUrlChange={onTokenUrlChange}
        onScopesChange={onScopesChange}
      />,
    );

    fireEvent.change(screen.getByLabelText(/Issuer URL/i), {
      target: { value: "https://auth.example.com" },
    });
    expect(onIssuerUrlChange).toHaveBeenCalledWith("https://auth.example.com");

    fireEvent.change(screen.getByLabelText(/Client ID/i), { target: { value: "my-client-id" } });
    expect(onClientIdChange).toHaveBeenCalledWith("my-client-id");

    fireEvent.change(screen.getByLabelText(/Client Secret/i), {
      target: { value: "my-client-secret" },
    });
    expect(onClientSecretChange).toHaveBeenCalledWith("my-client-secret");

    fireEvent.change(screen.getByLabelText(/Token URL/i), {
      target: { value: "https://auth.example.com/token" },
    });
    expect(onTokenUrlChange).toHaveBeenCalledWith("https://auth.example.com/token");

    fireEvent.change(screen.getByLabelText(/Scopes/i), { target: { value: "read write" } });
    expect(onScopesChange).toHaveBeenCalledWith("read write");
  });

  it("should trigger callbacks for password grant fields", () => {
    const onUsernameChange = vi.fn();
    const onPasswordChange = vi.fn();

    render(
      <OAuth2Auth
        {...defaultProps}
        grantType="password"
        onUsernameChange={onUsernameChange}
        onPasswordChange={onPasswordChange}
      />,
    );

    fireEvent.change(screen.getByLabelText(/Username/i), { target: { value: "test-user" } });
    expect(onUsernameChange).toHaveBeenCalledWith("test-user");

    fireEvent.change(screen.getByLabelText(/Password/i), { target: { value: "test-pass" } });
    expect(onPasswordChange).toHaveBeenCalledWith("test-pass");
  });

  it("should trigger callbacks for authorization_code fields", () => {
    const onRedirectUriChange = vi.fn();
    const onAuthorizationUrlChange = vi.fn();

    render(
      <OAuth2Auth
        {...defaultProps}
        grantType="authorization_code"
        onRedirectUriChange={onRedirectUriChange}
        onAuthorizationUrlChange={onAuthorizationUrlChange}
      />,
    );

    fireEvent.change(screen.getByLabelText(/Redirect URI/i), {
      target: { value: "https://redirect.com" },
    });
    expect(onRedirectUriChange).toHaveBeenCalledWith("https://redirect.com");

    fireEvent.change(screen.getByLabelText(/Authorization URL/i), {
      target: { value: "https://auth.com/authorize" },
    });
    expect(onAuthorizationUrlChange).toHaveBeenCalledWith("https://auth.com/authorize");
  });

  it("should trigger checkbox callback functions", () => {
    const onStoreTokensChange = vi.fn();
    const onAutoRefreshChange = vi.fn();

    render(
      <OAuth2Auth
        {...defaultProps}
        onStoreTokensChange={onStoreTokensChange}
        onAutoRefreshChange={onAutoRefreshChange}
      />,
    );

    fireEvent.click(screen.getByLabelText(/Store access tokens for reuse/i));
    expect(onStoreTokensChange).toHaveBeenCalled();

    fireEvent.click(screen.getByLabelText(/Automatically refresh expired tokens/i));
    expect(onAutoRefreshChange).toHaveBeenCalled();
  });
});
