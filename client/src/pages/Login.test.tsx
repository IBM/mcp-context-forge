import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { Login } from "./Login";
import { useAuth } from "../auth/useAuth";
import { useRouter } from "../router";
import { ApiError } from "../api/client";
import { I18nProvider } from "@/i18n";
import type { ReactElement } from "react";

// Mock hooks
vi.mock("../auth/useAuth", () => ({
  useAuth: vi.fn(),
}));

vi.mock("../router", () => ({
  useRouter: vi.fn(),
}));

function renderWithI18n(ui: ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>);
}

describe("Login", () => {
  const mockNavigate = vi.fn();
  const mockLogin = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useRouter).mockReturnValue({
      navigate: mockNavigate,
    } as unknown as ReturnType<typeof useRouter>);
  });

  it("redirects to /app/ if already authenticated", () => {
    vi.mocked(useAuth).mockReturnValue({
      isAuthenticated: true,
      login: mockLogin,
    } as unknown as ReturnType<typeof useAuth>);

    renderWithI18n(<Login />);

    expect(mockNavigate).toHaveBeenCalledWith("/app/");
  });

  it("renders login form correctly when unauthenticated", () => {
    vi.mocked(useAuth).mockReturnValue({
      isAuthenticated: false,
      login: mockLogin,
    } as unknown as ReturnType<typeof useAuth>);

    renderWithI18n(<Login />);

    expect(screen.getByLabelText(/Email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Password/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Sign in/i })).toBeInTheDocument();
  });

  it("handles successful login submission", async () => {
    vi.mocked(useAuth).mockReturnValue({
      isAuthenticated: false,
      login: mockLogin.mockResolvedValue(undefined),
    } as unknown as ReturnType<typeof useAuth>);

    renderWithI18n(<Login />);

    fireEvent.change(screen.getByLabelText(/Email/i), { target: { value: "test@example.com" } });
    fireEvent.change(screen.getByLabelText(/Password/i), { target: { value: "password123" } });
    fireEvent.submit(screen.getByRole("button", { name: /Sign in/i }));

    expect(screen.getByRole("button", { name: /Signing in…/i })).toBeInTheDocument();

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith("test@example.com", "password123");
      expect(mockNavigate).toHaveBeenCalledWith("/app/");
    });
  });

  it("displays invalid credentials error on 401 ApiError", async () => {
    const error = new ApiError("ApiError") as ApiError & { status?: number };
    error.status = 401;

    vi.mocked(useAuth).mockReturnValue({
      isAuthenticated: false,
      login: mockLogin.mockRejectedValue(error),
    } as unknown as ReturnType<typeof useAuth>);

    renderWithI18n(<Login />);

    fireEvent.change(screen.getByLabelText(/Email/i), { target: { value: "test@example.com" } });
    fireEvent.change(screen.getByLabelText(/Password/i), { target: { value: "wrongpass" } });
    fireEvent.submit(screen.getByRole("button", { name: /Sign in/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Invalid credentials.");
    });
  });

  it("displays generic failed error on non-401 ApiError", async () => {
    const error = new ApiError("ApiError") as ApiError & { status?: number };
    error.status = 500;

    vi.mocked(useAuth).mockReturnValue({
      isAuthenticated: false,
      login: mockLogin.mockRejectedValue(error),
    } as unknown as ReturnType<typeof useAuth>);

    renderWithI18n(<Login />);

    fireEvent.change(screen.getByLabelText(/Email/i), { target: { value: "test@example.com" } });
    fireEvent.change(screen.getByLabelText(/Password/i), { target: { value: "pass" } });
    fireEvent.submit(screen.getByRole("button", { name: /Sign in/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Login failed (500).");
    });
  });

  it("displays unexpected error on generic Error", async () => {
    vi.mocked(useAuth).mockReturnValue({
      isAuthenticated: false,
      login: mockLogin.mockRejectedValue(new Error("Generic network error")),
    } as unknown as ReturnType<typeof useAuth>);

    renderWithI18n(<Login />);

    fireEvent.change(screen.getByLabelText(/Email/i), { target: { value: "test@example.com" } });
    fireEvent.change(screen.getByLabelText(/Password/i), { target: { value: "pass" } });
    fireEvent.submit(screen.getByRole("button", { name: /Sign in/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("An unexpected error occurred.");
    });
  });

  it("navigates to forgot password page when forgot password link is clicked", () => {
    vi.mocked(useAuth).mockReturnValue({
      isAuthenticated: false,
      login: mockLogin,
    } as unknown as ReturnType<typeof useAuth>);

    renderWithI18n(<Login />);

    fireEvent.click(screen.getByRole("button", { name: /Forgot password\?/i }));
    expect(mockNavigate).toHaveBeenCalledWith("/app/forgot-password");
  });
});
