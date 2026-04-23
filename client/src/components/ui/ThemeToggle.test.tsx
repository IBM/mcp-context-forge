import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider } from "../../hooks/useTheme";
import { ThemeToggle } from "./ThemeToggle";

describe("ThemeToggle", () => {
  beforeEach(() => {
    // Clear localStorage manually
    Object.keys(localStorage).forEach((key) => localStorage.removeItem(key));
    document.documentElement.className = "";
  });

  it("should render theme toggle button", () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );

    const button = screen.getByRole("button");
    expect(button).toBeInTheDocument();
  });

  it("should show sun icon for light theme", () => {
    localStorage.setItem("theme-preference", "light");

    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );

    const button = screen.getByRole("button");
    expect(button).toHaveAttribute("aria-label", "Switch to dark mode");
  });

  it("should show moon icon for dark theme", () => {
    localStorage.setItem("theme-preference", "dark");

    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );

    const button = screen.getByRole("button");
    expect(button).toHaveAttribute("aria-label", "Switch to system theme");
  });

  it("should show monitor icon for system theme", () => {
    localStorage.setItem("theme-preference", "system");

    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );

    const button = screen.getByRole("button");
    expect(button).toHaveAttribute("aria-label", "Switch to light mode");
  });

  it("should cycle through themes on click", async () => {
    const user = userEvent.setup();

    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );

    const button = screen.getByRole("button");

    // Initial state should be system (gets persisted on mount)
    expect(localStorage.getItem("theme-preference")).toBe("system");

    // Click to go to light
    await user.click(button);
    expect(localStorage.getItem("theme-preference")).toBe("light");
    expect(button).toHaveAttribute("aria-label", "Switch to dark mode");

    // Click to go to dark
    await user.click(button);
    expect(localStorage.getItem("theme-preference")).toBe("dark");
    expect(button).toHaveAttribute("aria-label", "Switch to system theme");

    // Click to go to system
    await user.click(button);
    expect(localStorage.getItem("theme-preference")).toBe("system");
    expect(button).toHaveAttribute("aria-label", "Switch to light mode");

    // Click to go back to light
    await user.click(button);
    expect(localStorage.getItem("theme-preference")).toBe("light");
    expect(button).toHaveAttribute("aria-label", "Switch to dark mode");
  });

  it.skip("should apply correct CSS classes when cycling themes", async () => {
    const user = userEvent.setup();

    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );

    const button = screen.getByRole("button");

    // Initial state - system theme (defaults to light in test env)
    expect(document.documentElement.classList.contains("light")).toBe(true);

    // Click to light (explicit)
    await user.click(button);
    expect(document.documentElement.classList.contains("light")).toBe(true);
    expect(document.documentElement.classList.contains("dark")).toBe(false);

    // Click to dark
    await user.click(button);
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(document.documentElement.classList.contains("light")).toBe(false);
  });

  it("should have proper accessibility attributes", () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );

    const button = screen.getByRole("button");
    expect(button).toHaveAttribute("aria-label");
    expect(button).toHaveAttribute("title");
  });

  it("should use ghost variant and icon-sm size", () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );

    const button = screen.getByRole("button");
    expect(button).toHaveAttribute("data-variant", "ghost");
    expect(button).toHaveAttribute("data-size", "icon-sm");
  });
});
