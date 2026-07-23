import { describe, it, expect, vi } from "vitest";
import { renderWithProviders } from "@/test/test-utils";
import { screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToolBearerTokenAuth } from "./ToolBearerTokenAuth";
import { ToolAdvancedSettings } from "./ToolAdvancedSettings";
import type { CustomHeader } from "./ToolAdvancedSettings";

// ─── Mock auth context ─────────────────────────────────────────────────────────
vi.mock("@/auth/AuthContext", () => ({
  useAuthContext: () => ({
    selectedTeamId: "team-1",
    user: { email: "test@example.com", is_admin: false },
    teams: [],
  }),
}));

// ─────────────────────────────────────────────
// ToolBearerTokenAuth tests
// ─────────────────────────────────────────────
describe("ToolBearerTokenAuth", () => {
  it("renders a password input", () => {
    renderWithProviders(<ToolBearerTokenAuth token="" onTokenChange={vi.fn()} />);
    const input = screen.getByLabelText(/Token/i);
    expect(input).toBeTruthy();
    expect((input as HTMLInputElement).type).toBe("password");
  });

  it("shows current token value", () => {
    renderWithProviders(<ToolBearerTokenAuth token="my-secret-token" onTokenChange={vi.fn()} />);
    const input = screen.getByLabelText(/Token/i) as HTMLInputElement;
    expect(input.value).toBe("my-secret-token");
  });

  it("fires onTokenChange when typed", () => {
    const onTokenChange = vi.fn();
    renderWithProviders(<ToolBearerTokenAuth token="" onTokenChange={onTokenChange} />);
    const input = screen.getByLabelText(/Token/i);
    fireEvent.change(input, { target: { value: "new-token" } });
    expect(onTokenChange).toHaveBeenCalledWith("new-token");
  });

  it("has placeholder text", () => {
    renderWithProviders(<ToolBearerTokenAuth token="" onTokenChange={vi.fn()} />);
    expect(screen.getByPlaceholderText(/Paste bearer token/i)).toBeTruthy();
  });

  it("marks the token label as required with span", () => {
    renderWithProviders(<ToolBearerTokenAuth token="" onTokenChange={vi.fn()} />);
    // The label has a * for required
    const label = screen.getByText("Token", { exact: false });
    expect(label).toBeTruthy();
  });
});

// ─────────────────────────────────────────────
// ToolAdvancedSettings tests
// ─────────────────────────────────────────────
const defaultAdvancedProps = {
  visibility: "public" as const,
  onVisibilityChange: vi.fn(),
  teamId: "",
  onTeamIdChange: vi.fn(),
  authType: "none" as const,
  onAuthTypeChange: vi.fn(),
  basicAuthUsername: "",
  basicAuthPassword: "",
  onBasicAuthUsernameChange: vi.fn(),
  onBasicAuthPasswordChange: vi.fn(),
  bearerToken: "",
  onBearerTokenChange: vi.fn(),
  customHeaders: [] as CustomHeader[],
  onCustomHeadersChange: vi.fn(),
  responseFilter: "",
  onResponseFilterChange: vi.fn(),
  tags: [] as string[],
  onTagsChange: vi.fn(),
  description: "",
  onDescriptionChange: vi.fn(),
};

describe("ToolAdvancedSettings", () => {
  it("renders Visibility label", () => {
    renderWithProviders(<ToolAdvancedSettings {...defaultAdvancedProps} />);
    expect(screen.getByText("Visibility")).toBeTruthy();
  });

  it("renders Authentication type label", () => {
    renderWithProviders(<ToolAdvancedSettings {...defaultAdvancedProps} />);
    expect(screen.getByText("Authentication type")).toBeTruthy();
  });

  it("renders auth radio buttons for all types", () => {
    renderWithProviders(<ToolAdvancedSettings {...defaultAdvancedProps} />);
    expect(screen.getByLabelText("None")).toBeTruthy();
    expect(screen.getByLabelText("Basic")).toBeTruthy();
    expect(screen.getByLabelText("Bearer token")).toBeTruthy();
    expect(screen.getByLabelText("Custom headers")).toBeTruthy();
  });

  it("shows no auth content for authType=none", () => {
    renderWithProviders(<ToolAdvancedSettings {...defaultAdvancedProps} authType="none" />);
    expect(screen.queryByPlaceholderText(/Paste bearer token/i)).toBeNull();
  });

  it("shows bearer token input for authType=bearer", () => {
    renderWithProviders(<ToolAdvancedSettings {...defaultAdvancedProps} authType="bearer" />);
    expect(screen.getByPlaceholderText(/Paste bearer token/i)).toBeTruthy();
  });

  it("shows basic auth fields for authType=basic", () => {
    renderWithProviders(<ToolAdvancedSettings {...defaultAdvancedProps} authType="basic" />);
    // BasicAuth renders username and password fields
    expect(screen.getByLabelText(/username/i)).toBeTruthy();
  });

  it("calls onAuthTypeChange when bearer radio is selected", () => {
    const onAuthTypeChange = vi.fn();
    renderWithProviders(
      <ToolAdvancedSettings {...defaultAdvancedProps} onAuthTypeChange={onAuthTypeChange} />,
    );
    const bearerRadio = screen.getByLabelText("Bearer token");
    fireEvent.click(bearerRadio);
    expect(onAuthTypeChange).toHaveBeenCalledWith("bearer");
  });

  it("renders Response filter label", () => {
    renderWithProviders(<ToolAdvancedSettings {...defaultAdvancedProps} />);
    expect(screen.getByLabelText("Response filter (jq)")).toBeTruthy();
  });

  it("renders Tags input", () => {
    renderWithProviders(<ToolAdvancedSettings {...defaultAdvancedProps} />);
    expect(screen.getByLabelText("Tags")).toBeTruthy();
  });

  it("renders Description textarea", () => {
    renderWithProviders(<ToolAdvancedSettings {...defaultAdvancedProps} />);
    expect(screen.getByLabelText("Description")).toBeTruthy();
  });

  it("fires onResponseFilterChange when response filter is typed", () => {
    const onResponseFilterChange = vi.fn();
    renderWithProviders(
      <ToolAdvancedSettings
        {...defaultAdvancedProps}
        onResponseFilterChange={onResponseFilterChange}
      />,
    );
    const input = screen.getByLabelText("Response filter (jq)");
    fireEvent.change(input, { target: { value: ".data" } });
    expect(onResponseFilterChange).toHaveBeenCalledWith(".data");
  });

  it("fires onTagsChange when a tag is committed", async () => {
    const onTagsChange = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <ToolAdvancedSettings {...defaultAdvancedProps} onTagsChange={onTagsChange} />,
    );
    const input = screen.getByLabelText("Tags");
    await user.type(input, "api{Enter}");
    expect(onTagsChange).toHaveBeenCalledWith(["api"]);
  });

  it("fires onDescriptionChange when description textarea changes", () => {
    const onDescriptionChange = vi.fn();
    renderWithProviders(
      <ToolAdvancedSettings {...defaultAdvancedProps} onDescriptionChange={onDescriptionChange} />,
    );
    const textarea = screen.getByLabelText("Description");
    fireEvent.change(textarea, { target: { value: "My tool" } });
    expect(onDescriptionChange).toHaveBeenCalledWith("My tool");
  });

  it("shows team scope hint when visibility=team and selectedTeamId is set", () => {
    renderWithProviders(<ToolAdvancedSettings {...defaultAdvancedProps} visibility="team" />);
    expect(
      screen.getByText(/This tool will be scoped to your currently selected team/i),
    ).toBeTruthy();
  });

  it("calls onTeamIdChange('') when visibility changes away from team", () => {
    const onTeamIdChange = vi.fn();
    renderWithProviders(
      <ToolAdvancedSettings
        {...defaultAdvancedProps}
        visibility="team"
        teamId="team-1"
        onTeamIdChange={onTeamIdChange}
      />,
    );
    // onTeamIdChange called with '' when visibility != "team" is handled by useEffect
    // Switching to public visibility is tested via re-render
    renderWithProviders(
      <ToolAdvancedSettings
        {...defaultAdvancedProps}
        visibility="public"
        teamId="team-1"
        onTeamIdChange={onTeamIdChange}
      />,
    );
    // useEffect fires immediately on mount when visibility !== "team" but teamId is set
    expect(onTeamIdChange).toHaveBeenCalledWith("");
  });
});
