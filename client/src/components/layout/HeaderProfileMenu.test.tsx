import { describe, expect, it, vi, beforeEach } from "vitest";
import userEvent from "@testing-library/user-event";
import { ThemeProvider } from "@/hooks/useTheme";
import { I18nProvider } from "@/i18n";
import { render, screen } from "@testing-library/react";
import { HeaderProfileMenu } from "./HeaderProfileMenu";

const mockLogout = vi.fn();
const mockNavigate = vi.fn();

vi.mock("@/auth/useAuth", () => ({
  useAuth: () => ({
    user: {
      email: "bobo@cf.com",
      full_name: "Bobo Example",
      is_admin: false,
      is_active: true,
      auth_provider: "local",
      email_verified: true,
      password_change_required: false,
    },
    logout: mockLogout,
  }),
}));

vi.mock("@/router", async () => {
  const actual = await vi.importActual<typeof import("@/router")>("@/router");
  return {
    ...actual,
    useRouter: () => ({
      path: "/app/",
      params: {},
      navigate: mockNavigate,
    }),
  };
});

describe("HeaderProfileMenu", () => {
  beforeEach(() => {
    mockLogout.mockReset();
    mockNavigate.mockReset();
    localStorage.clear();
  });

  function renderMenu() {
    return render(
      <I18nProvider>
        <ThemeProvider>
          <HeaderProfileMenu />
        </ThemeProvider>
      </I18nProvider>,
    );
  }

  it("renders the profile trigger", () => {
    renderMenu();
    expect(screen.getByRole("button", { name: "Bobo Example" })).toBeInTheDocument();
  });

  it("navigates to settings from the dropdown", async () => {
    const user = userEvent.setup();
    renderMenu();

    await user.click(screen.getByRole("button", { name: "Bobo Example" }));
    await user.click(screen.getByText("Settings"));

    expect(mockNavigate).toHaveBeenCalledWith("/app/settings");
  });

  it("logs out from the dropdown", async () => {
    const user = userEvent.setup();
    renderMenu();

    await user.click(screen.getByRole("button", { name: "Bobo Example" }));
    await user.click(screen.getByText("Sign Out"));

    expect(mockLogout).toHaveBeenCalled();
  });

  it("updates the saved theme preference", async () => {
    const user = userEvent.setup();
    renderMenu();

    await user.click(screen.getByRole("button", { name: "Bobo Example" }));
    await user.click(screen.getByRole("button", { name: "Dark mode" }));

    expect(localStorage.getItem("theme-preference")).toBe("dark");
  });

  it("supports switching back to light mode", async () => {
    const user = userEvent.setup();
    localStorage.setItem("theme-preference", "dark");
    renderMenu();

    await user.click(screen.getByRole("button", { name: "Bobo Example" }));
    await user.click(screen.getByRole("button", { name: "Light mode" }));

    expect(localStorage.getItem("theme-preference")).toBe("light");
  });

  it("supports switching to system theme", async () => {
    const user = userEvent.setup();
    renderMenu();

    await user.click(screen.getByRole("button", { name: "Bobo Example" }));
    await user.click(screen.getByRole("button", { name: "System theme" }));

    expect(localStorage.getItem("theme-preference")).toBe("system");
  });
});
