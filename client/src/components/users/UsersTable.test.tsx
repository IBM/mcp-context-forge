import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { IntlProvider } from "react-intl";
import { UsersTable } from "./UsersTable";
import type { User } from "../../types/user";

const mockIntl = {
  locale: "en-US",
  messages: {
    "users.date.never": "Never",
    "users.unnamed": "Unnamed User",
    "users.table.caption": "Users",
    "users.table.user": "User",
    "users.table.role": "Role",
    "users.table.status": "Status",
    "users.table.provider": "Provider",
    "users.table.security": "Security",
    "users.table.created": "Created",
    "users.table.lastLogin": "Last Login",
    "users.role.admin": "Admin",
    "users.role.user": "User",
    "users.status.active": "Active",
    "users.status.inactive": "Inactive",
    "users.security.noFlags": "No Flags",
    "users.security.locked": "Locked",
    "users.security.passwordReset": "Password Reset",
    "users.security.verified": "Verified",
  },
};

const renderWithIntl = (component: React.ReactNode) => {
  return render(
    <IntlProvider locale={mockIntl.locale} messages={mockIntl.messages}>
      {component}
    </IntlProvider>
  );
};

const baseUser: User = {
  email: "test@example.com",
  full_name: "Test User",
  auth_provider: "local",
  is_admin: false,
  is_active: true,
  is_locked: false,
  password_change_required: false,
  email_verified: false,
  created_at: "2023-01-01T10:00:00Z",
  last_login: "2023-01-02T10:00:00Z",
};

describe("UsersTable", () => {
  it("renders user information correctly", () => {
    renderWithIntl(<UsersTable users={[baseUser]} />);
    
    expect(screen.getByText("Test User")).toBeInTheDocument();
    expect(screen.getByText("test@example.com")).toBeInTheDocument();
    expect(screen.getByText("Local")).toBeInTheDocument(); // Provider
    expect(screen.getAllByText("User")).toHaveLength(2); // Role and Header
    expect(screen.getByText("Active")).toBeInTheDocument(); // Status
    expect(screen.getByText("No Flags")).toBeInTheDocument(); // Security
  });

  it("handles missing full name by showing unnamed fallback", () => {
    const user: User = { ...baseUser, full_name: "", email: "unnamed@example.com" };
    renderWithIntl(<UsersTable users={[user]} />);
    expect(screen.getByText("Unnamed User")).toBeInTheDocument();
  });

  it("renders admin role and inactive status correctly", () => {
    const user: User = { ...baseUser, email: "admin@example.com", is_admin: true, is_active: false };
    renderWithIntl(<UsersTable users={[user]} />);
    expect(screen.getByText("Admin")).toBeInTheDocument();
    expect(screen.getByText("Inactive")).toBeInTheDocument();
  });

  it("renders locked security state", () => {
    const user: User = { ...baseUser, is_locked: true, password_change_required: true, email_verified: true };
    renderWithIntl(<UsersTable users={[user]} />);
    expect(screen.getByText("Locked")).toBeInTheDocument();
  });

  it("renders password reset security state", () => {
    const user: User = { ...baseUser, password_change_required: true, email_verified: true };
    renderWithIntl(<UsersTable users={[user]} />);
    expect(screen.getByText("Password Reset")).toBeInTheDocument();
  });

  it("renders verified security state", () => {
    const user: User = { ...baseUser, email_verified: true };
    renderWithIntl(<UsersTable users={[user]} />);
    expect(screen.getByText("Verified")).toBeInTheDocument();
  });

  it("handles empty date strings", () => {
    const user: User = { ...baseUser, created_at: "", last_login: null as any };
    renderWithIntl(<UsersTable users={[user]} />);
    expect(screen.getAllByText("Never")).toHaveLength(2);
  });

  it("handles invalid date strings gracefully", () => {
    const user: User = { ...baseUser, created_at: "invalid-date", last_login: "not-a-date" };
    renderWithIntl(<UsersTable users={[user]} />);
    expect(screen.getByText("invalid-date")).toBeInTheDocument();
    expect(screen.getByText("not-a-date")).toBeInTheDocument();
  });

  it("catches exception during date formatting", () => {
    const originalDate = global.Date;
    const mockDate = vi.fn(() => {
      throw new Error("Date error");
    }) as any;
    mockDate.now = originalDate.now;
    global.Date = mockDate;

    const user: User = { ...baseUser, created_at: "error-date" };
    renderWithIntl(<UsersTable users={[user]} />);
    expect(screen.getByText("error-date")).toBeInTheDocument();

    global.Date = originalDate;
  });
});
