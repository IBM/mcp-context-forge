import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NoneAuth } from "./NoneAuth";
import { BasicAuth } from "./BasicAuth";
import { BearerTokenAuth } from "./BearerTokenAuth";
import { QueryParameterAuth } from "./QueryParameterAuth";

describe("Auth Components", () => {
  describe("NoneAuth", () => {
    it("renders the no-credentials message", () => {
      render(<NoneAuth />);
      expect(screen.getByText(/No credentials are required/i)).toBeTruthy();
    });

    it("renders the production security checklist link", () => {
      render(<NoneAuth />);
      const link = screen.getByRole("link", { name: /Production Security Checklist/i });
      expect(link).toBeTruthy();
      expect(link.getAttribute("href")).toContain("mcp-context-forge");
      expect(link.getAttribute("target")).toBe("_blank");
      expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    });

    it("renders a zap icon container", () => {
      const { container } = render(<NoneAuth />);
      expect(container.querySelector("svg")).toBeTruthy();
    });
  });

  describe("BasicAuth", () => {
    const defaultProps = {
      username: "",
      password: "", // pragma: allowlist secret
      onUsernameChange: vi.fn(),
      onPasswordChange: vi.fn(),
    };

    it("renders username and password fields", () => {
      render(<BasicAuth {...defaultProps} />);
      expect(screen.getByLabelText(/Username/i)).toBeTruthy();
      expect(screen.getByLabelText(/Password/i)).toBeTruthy();
    });

    it("shows current username value", () => {
      render(<BasicAuth {...defaultProps} username="admin" />);
      const input = screen.getByLabelText(/Username/i) as HTMLInputElement;
      expect(input.value).toBe("admin");
    });

    it("calls onUsernameChange when username changes", () => {
      const onUsernameChange = vi.fn();
      render(<BasicAuth {...defaultProps} onUsernameChange={onUsernameChange} />);
      const input = screen.getByLabelText(/Username/i);
      fireEvent.change(input, { target: { value: "newuser" } });
      expect(onUsernameChange).toHaveBeenCalledWith("newuser");
    });

    it("calls onPasswordChange when password changes", () => {
      const onPasswordChange = vi.fn();
      render(<BasicAuth {...defaultProps} onPasswordChange={onPasswordChange} />);
      const input = screen.getByLabelText(/Password/i);
      fireEvent.change(input, { target: { value: "secret" } }); // pragma: allowlist secret
      expect(onPasswordChange).toHaveBeenCalledWith("secret");
    });

    it("password input is type password", () => {
      render(<BasicAuth {...defaultProps} />);
      const input = screen.getByLabelText(/Password/i) as HTMLInputElement;
      expect(input.type).toBe("password");
    });

    it("renders required indicators for both fields", () => {
      render(<BasicAuth {...defaultProps} />);
      // Both fields have * required markers
      const stars = screen.getAllByText("*");
      expect(stars.length).toBeGreaterThanOrEqual(2);
    });
  });

  describe("BearerTokenAuth", () => {
    it("renders bearer token label and description", () => {
      render(<BearerTokenAuth token="" onTokenChange={vi.fn()} />);
      expect(screen.getByText(/Bearer token/i)).toBeTruthy();
      expect(screen.getByText(/API key or token/i)).toBeTruthy();
    });

    it("renders the token input with password type", () => {
      render(<BearerTokenAuth token="my-secret" onTokenChange={vi.fn()} />); // pragma: allowlist secret
      const input = screen.getByPlaceholderText(/Paste bearer token/i) as HTMLInputElement;
      expect(input.type).toBe("password");
      expect(input.value).toBe("my-secret");
    });

    it("calls onTokenChange when token input changes", () => {
      const onTokenChange = vi.fn();
      render(<BearerTokenAuth token="" onTokenChange={onTokenChange} />);
      const input = screen.getByPlaceholderText(/Paste bearer token/i);
      fireEvent.change(input, { target: { value: "abc123" } });
      expect(onTokenChange).toHaveBeenCalledWith("abc123");
    });

    it("renders with empty initial token", () => {
      render(<BearerTokenAuth token="" onTokenChange={vi.fn()} />);
      const input = screen.getByPlaceholderText(/Paste bearer token/i) as HTMLInputElement;
      expect(input.value).toBe("");
    });
  });

  describe("QueryParameterAuth", () => {
    const defaultProps = {
      parameterName: "",
      apiKey: "",
      onParameterNameChange: vi.fn(),
      onApiKeyChange: vi.fn(),
    };

    it("renders the security warning", () => {
      render(<QueryParameterAuth {...defaultProps} />);
      expect(screen.getByText(/Security Warning/i)).toBeTruthy();
      expect(screen.getByText(/proxy logs/i)).toBeTruthy();
    });

    it("renders query parameter name and API key fields", () => {
      render(<QueryParameterAuth {...defaultProps} />);
      expect(screen.getByLabelText(/Query parameter name/i)).toBeTruthy();
      expect(screen.getByLabelText(/API key/i)).toBeTruthy();
    });

    it("shows current parameterName value", () => {
      render(<QueryParameterAuth {...defaultProps} parameterName="api_key" />);
      const input = screen.getByLabelText(/Query parameter name/i) as HTMLInputElement;
      expect(input.value).toBe("api_key");
    });

    it("calls onParameterNameChange when param name changes", () => {
      const onParameterNameChange = vi.fn();
      render(
        <QueryParameterAuth {...defaultProps} onParameterNameChange={onParameterNameChange} />,
      );
      const input = screen.getByLabelText(/Query parameter name/i);
      fireEvent.change(input, { target: { value: "token" } });
      expect(onParameterNameChange).toHaveBeenCalledWith("token");
    });

    it("calls onApiKeyChange when API key changes", () => {
      const onApiKeyChange = vi.fn();
      render(<QueryParameterAuth {...defaultProps} onApiKeyChange={onApiKeyChange} />);
      const input = screen.getByLabelText(/API key/i);
      fireEvent.change(input, { target: { value: "xyz789" } });
      expect(onApiKeyChange).toHaveBeenCalledWith("xyz789");
    });

    it("API key input is type password", () => {
      render(<QueryParameterAuth {...defaultProps} />);
      const input = screen.getByLabelText(/API key/i) as HTMLInputElement;
      expect(input.type).toBe("password");
    });

    it("query param name input is type text", () => {
      render(<QueryParameterAuth {...defaultProps} />);
      const input = screen.getByLabelText(/Query parameter name/i) as HTMLInputElement;
      expect(input.type).toBe("text");
    });

    it("renders required indicators", () => {
      render(<QueryParameterAuth {...defaultProps} />);
      const stars = screen.getAllByText("*");
      expect(stars.length).toBeGreaterThanOrEqual(2);
    });

    it("renders alert triangle icon for security warning", () => {
      const { container } = render(<QueryParameterAuth {...defaultProps} />);
      expect(container.querySelector("svg")).toBeTruthy();
    });
  });
});
