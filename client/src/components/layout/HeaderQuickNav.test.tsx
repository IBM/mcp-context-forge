import { describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { render, screen } from "@testing-library/react";
import { I18nProvider } from "@/i18n";
import { HeaderQuickNav } from "./HeaderQuickNav";

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
});
