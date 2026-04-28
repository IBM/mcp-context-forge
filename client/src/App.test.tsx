import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "./App";
import { renderWithProviders } from "./test/test-utils";

describe("App", () => {
  it("logs in and navigates to Gateways page via sidebar", async () => {
    const user = userEvent.setup();

    // Clear any existing auth
    localStorage.clear();
    sessionStorage.clear();
    window.history.pushState({}, "", "/app/login");

    renderWithProviders(<App />);

    // Wait for login page to render
    await screen.findByRole("heading", { name: /sign in/i });

    // Fill in login form
    const emailInput = screen.getByLabelText(/email address/i);
    const passwordInput = screen.getByLabelText(/password/i);
    const submitButton = screen.getByRole("button", { name: /sign in/i });

    await user.type(emailInput, "test@example.com");
    await user.type(passwordInput, "password123");
    await user.click(submitButton);

    // Wait for dashboard to load after successful login
    await screen.findByRole("heading", { name: /dashboard/i });

    // Click on Gateways in the sidebar
    const gatewaysLink = screen.getByRole("button", { name: /gateways/i });
    await user.click(gatewaysLink);

    // Verify Gateways page is displayed
    const gatewaysHeading = await screen.findByRole("heading", { name: /Connect a source/i });
    expect(gatewaysHeading).toBeInTheDocument();
  });
});
