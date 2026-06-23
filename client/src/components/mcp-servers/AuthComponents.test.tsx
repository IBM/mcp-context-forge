import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BasicAuth } from "./BasicAuth";
import { BearerTokenAuth } from "./BearerTokenAuth";
import { QueryParameterAuth } from "./QueryParameterAuth";

describe("Auth Components", () => {
  describe("BasicAuth", () => {
    it("calls change handlers on input", () => {
      const onUsernameChange = vi.fn();
      const onPasswordChange = vi.fn();

      render(
        <BasicAuth
          username=""
          password=""
          onUsernameChange={onUsernameChange}
          onPasswordChange={onPasswordChange}
        />,
      );

      const usernameInput = screen.getByLabelText(/Username/i);
      const passwordInput = screen.getByLabelText(/Password/i);

      // Use fireEvent.change to simulate a complete value change on a controlled component
      fireEvent.change(usernameInput, { target: { value: "testuser" } });
      expect(onUsernameChange).toHaveBeenCalledWith("testuser");

      fireEvent.change(passwordInput, { target: { value: "testpass" } });
      expect(onPasswordChange).toHaveBeenCalledWith("testpass");
    });
  });

  describe("BearerTokenAuth", () => {
    it("calls change handler on input", () => {
      const onTokenChange = vi.fn();

      render(<BearerTokenAuth token="" onTokenChange={onTokenChange} />);

      const tokenInput = screen.getByLabelText(/Bearer token/i);

      // Use fireEvent.change to simulate a complete value change on a controlled component
      fireEvent.change(tokenInput, { target: { value: "testtoken" } });
      expect(onTokenChange).toHaveBeenCalledWith("testtoken");
    });
  });

  describe("QueryParameterAuth", () => {
    it("calls change handlers on input", () => {
      const onParameterNameChange = vi.fn();
      const onApiKeyChange = vi.fn();

      render(
        <QueryParameterAuth
          parameterName=""
          apiKey=""
          onParameterNameChange={onParameterNameChange}
          onApiKeyChange={onApiKeyChange}
        />,
      );

      const paramNameInput = screen.getByLabelText(/Query parameter name/i);
      const apiKeyInput = screen.getByLabelText(/API key/i);

      // Use fireEvent.change to simulate a complete value change on a controlled component
      fireEvent.change(paramNameInput, { target: { value: "api_key" } });
      expect(onParameterNameChange).toHaveBeenCalledWith("api_key");

      fireEvent.change(apiKeyInput, { target: { value: "testkey" } });
      expect(onApiKeyChange).toHaveBeenCalledWith("testkey");
    });
  });
});
