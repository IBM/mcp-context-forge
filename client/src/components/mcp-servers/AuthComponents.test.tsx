import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { BasicAuth } from "./BasicAuth";
import { BearerTokenAuth } from "./BearerTokenAuth";
import { QueryParameterAuth } from "./QueryParameterAuth";

describe("Auth Components", () => {
  describe("BasicAuth", () => {
    it("calls change handlers on input", async () => {
      const user = userEvent.setup();
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

      await user.type(usernameInput, "testuser");
      expect(onUsernameChange).toHaveBeenCalledWith("testuser");

      await user.type(passwordInput, "testpass");
      expect(onPasswordChange).toHaveBeenCalledWith("testpass");
    });
  });

  describe("BearerTokenAuth", () => {
    it("calls change handler on input", async () => {
      const user = userEvent.setup();
      const onTokenChange = vi.fn();

      render(<BearerTokenAuth token="" onTokenChange={onTokenChange} />);

      const tokenInput = screen.getByLabelText(/Bearer token/i);

      await user.type(tokenInput, "testtoken");
      expect(onTokenChange).toHaveBeenCalledWith("testtoken");
    });
  });

  describe("QueryParameterAuth", () => {
    it("calls change handlers on input", async () => {
      const user = userEvent.setup();
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

      await user.type(paramNameInput, "api_key");
      expect(onParameterNameChange).toHaveBeenCalledWith("api_key");

      await user.type(apiKeyInput, "testkey");
      expect(onApiKeyChange).toHaveBeenCalledWith("testkey");
    });
  });
});
