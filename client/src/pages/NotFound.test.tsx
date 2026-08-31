import { describe, it, expect, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "@testing-library/react";
import { NotFound } from "./NotFound";
import { RouterProvider } from "@/router";
import { I18nProvider } from "@/i18n";
import type { ReactElement } from "react";

// Helper to render with real router
function renderWithRouter(ui: ReactElement) {
  // Set up initial route
  window.history.pushState({}, "", "/app/not-found");

  return render(
    <RouterProvider>
      <I18nProvider>{ui}</I18nProvider>
    </RouterProvider>,
  );
}

describe("NotFound", () => {
  beforeEach(() => {
    // Clear any previous history state
    window.history.replaceState({}, "", "/app/");
  });

  it("renders 404 text", () => {
    renderWithRouter(<NotFound />);
    expect(screen.getByText("404")).toBeInTheDocument();
  });

  it("renders 'Page not found.' text", () => {
    renderWithRouter(<NotFound />);
    expect(screen.getByText("Page not found.")).toBeInTheDocument();
  });

  it("renders 'Go to Dashboard' button", () => {
    renderWithRouter(<NotFound />);
    const button = screen.getByRole("button", { name: /Go to Dashboard/i });
    expect(button).toBeInTheDocument();
  });

  it("navigates to /app/ when 'Go to Dashboard' button is clicked", async () => {
    const user = userEvent.setup();
    renderWithRouter(<NotFound />);

    const button = screen.getByRole("button", { name: /Go to Dashboard/i });
    await user.click(button);

    // Verify navigation occurred by checking window.location.pathname
    expect(window.location.pathname).toBe("/app/");
  });

  it("renders all elements together", () => {
    renderWithRouter(<NotFound />);

    expect(screen.getByText("404")).toBeInTheDocument();
    expect(screen.getByText("Page not found.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Go to Dashboard/i })).toBeInTheDocument();
  });
});
