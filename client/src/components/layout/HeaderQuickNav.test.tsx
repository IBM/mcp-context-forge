import { afterEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { fireEvent, render, screen } from "@testing-library/react";
import { I18nProvider } from "@/i18n";
import { HeaderQuickNav } from "./HeaderQuickNav";

const originalPlatform = window.navigator.platform;

afterEach(() => {
  Object.defineProperty(window.navigator, "platform", {
    configurable: true,
    value: originalPlatform,
  });
});

describe("HeaderQuickNav", () => {
  it("renders a search input", () => {
    render(
      <I18nProvider>
        <HeaderQuickNav />
      </I18nProvider>,
    );

    expect(screen.getByRole("searchbox", { name: "Search" })).toBeInTheDocument();
  });

  it("starts collapsed and expands on focus", async () => {
    const user = userEvent.setup();

    render(
      <I18nProvider>
        <HeaderQuickNav />
      </I18nProvider>,
    );

    const input = screen.getByRole("searchbox", { name: "Search" });
    expect(input).toHaveAttribute("data-expanded", "false");
    expect(screen.getByText("Ctrl K")).toBeInTheDocument();

    await user.click(input);

    expect(input).toHaveAttribute("data-expanded", "true");
  });

  it("keeps the typed value in the input", async () => {
    const user = userEvent.setup();

    render(
      <I18nProvider>
        <HeaderQuickNav />
      </I18nProvider>,
    );

    const input = screen.getByRole("searchbox", { name: "Search" });
    await user.type(input, "servers");

    expect(input).toHaveValue("servers");
  });

  it("focuses the search input when the icon button is clicked", async () => {
    const user = userEvent.setup();

    render(
      <I18nProvider>
        <HeaderQuickNav />
      </I18nProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(screen.getByRole("searchbox", { name: "Search" })).toHaveFocus();
  });

  it("shows the macOS shortcut symbol on Apple platforms", async () => {
    Object.defineProperty(window.navigator, "platform", {
      configurable: true,
      value: "MacIntel",
    });

    render(
      <I18nProvider>
        <HeaderQuickNav />
      </I18nProvider>,
    );

    expect(await screen.findByText("⌘ K")).toBeInTheDocument();
  });

  it("focuses the search input when the shortcut is pressed", () => {
    render(
      <I18nProvider>
        <HeaderQuickNav />
      </I18nProvider>,
    );

    const input = screen.getByRole("searchbox", { name: "Search" });
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });

    expect(input).toHaveFocus();
    expect(input).toHaveAttribute("data-expanded", "true");
  });

  it("stays expanded after blur when the query has content", async () => {
    const user = userEvent.setup();

    render(
      <I18nProvider>
        <HeaderQuickNav />
      </I18nProvider>,
    );

    const input = screen.getByRole("searchbox", { name: "Search" });
    await user.type(input, "servers");
    fireEvent.blur(input);

    expect(input).toHaveAttribute("data-expanded", "true");
  });

  it("collapses again on blur when the query is empty", async () => {
    const user = userEvent.setup();

    render(
      <I18nProvider>
        <HeaderQuickNav />
      </I18nProvider>,
    );

    const input = screen.getByRole("searchbox", { name: "Search" });
    await user.click(input);
    fireEvent.blur(input);

    expect(input).toHaveAttribute("data-expanded", "false");
  });

  it("prevents the form from submitting", () => {
    render(
      <I18nProvider>
        <HeaderQuickNav />
      </I18nProvider>,
    );

    const input = screen.getByRole("searchbox", { name: "Search" });
    const form = input.closest("form");
    expect(form).not.toBeNull();

    const submitEvent = new Event("submit", { bubbles: true, cancelable: true });
    form!.dispatchEvent(submitEvent);

    expect(submitEvent.defaultPrevented).toBe(true);
  });
});
