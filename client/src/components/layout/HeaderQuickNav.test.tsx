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
  });
});
