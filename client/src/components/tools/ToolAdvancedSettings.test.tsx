import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { renderWithProviders } from "@/test/test-utils";
import { ToolAdvancedSettings } from "./ToolAdvancedSettings";
import { ToolBearerTokenAuth } from "./ToolBearerTokenAuth";

// Mock AuthContext
vi.mock("@/auth/AuthContext", () => ({
  useAuthContext: () => ({
    selectedTeamId: "team-123",
    user: null,
    token: null,
  }),
}));

const defaultProps = {
  visibility: "public" as const,
  onVisibilityChange: vi.fn(),
  teamId: "",
  onTeamIdChange: vi.fn(),
  authType: "none" as const,
  onAuthTypeChange: vi.fn(),
  basicAuthUsername: "",
  basicAuthPassword: "", // pragma: allowlist secret
  onBasicAuthUsernameChange: vi.fn(),
  onBasicAuthPasswordChange: vi.fn(),
  bearerToken: "",
  onBearerTokenChange: vi.fn(),
  customHeaders: [],
  onCustomHeadersChange: vi.fn(),
  responseFilter: "",
  onResponseFilterChange: vi.fn(),
  tags: "",
  onTagsChange: vi.fn(),
  description: "",
  onDescriptionChange: vi.fn(),
};

describe("ToolBearerTokenAuth", () => {
  it("renders token label", () => {
    render(<ToolBearerTokenAuth token="" onTokenChange={vi.fn()} />);
    expect(screen.getByText("Token")).toBeTruthy();
  });

  it("renders required star", () => {
    render(<ToolBearerTokenAuth token="" onTokenChange={vi.fn()} />);
    expect(screen.getByText("*")).toBeTruthy();
  });

  it("renders password type input", () => {
    render(<ToolBearerTokenAuth token="" onTokenChange={vi.fn()} />);
    const input = screen.getByPlaceholderText(/Paste bearer token/i) as HTMLInputElement;
    expect(input.type).toBe("password");
  });

  it("displays current token value", () => {
    render(<ToolBearerTokenAuth token="abc123" onTokenChange={vi.fn()} />);
    const input = screen.getByPlaceholderText(/Paste bearer token/i) as HTMLInputElement;
    expect(input.value).toBe("abc123");
  });

  it("calls onTokenChange when input changes", () => {
    const onTokenChange = vi.fn();
    render(<ToolBearerTokenAuth token="" onTokenChange={onTokenChange} />);
    const input = screen.getByPlaceholderText(/Paste bearer token/i);
    fireEvent.change(input, { target: { value: "new-token" } });
    expect(onTokenChange).toHaveBeenCalledWith("new-token");
  });
});

describe("ToolAdvancedSettings", () => {
  it("renders visibility section", () => {
    renderWithProviders(<ToolAdvancedSettings {...defaultProps} />);
    expect(screen.getByText("Visibility")).toBeTruthy();
  });

  it("renders authentication type section", () => {
    renderWithProviders(<ToolAdvancedSettings {...defaultProps} />);
    expect(screen.getByText("Authentication type")).toBeTruthy();
  });

  it("renders all auth type options", () => {
    renderWithProviders(<ToolAdvancedSettings {...defaultProps} />);
    expect(screen.getByText("None")).toBeTruthy();
    expect(screen.getByText("Basic")).toBeTruthy();
    expect(screen.getByText("Bearer token")).toBeTruthy();
    expect(screen.getByText("Custom headers")).toBeTruthy();
  });

  it("renders response filter field", () => {
    renderWithProviders(<ToolAdvancedSettings {...defaultProps} />);
    expect(screen.getByLabelText(/Response filter/i)).toBeTruthy();
  });

  it("renders tags field", () => {
    renderWithProviders(<ToolAdvancedSettings {...defaultProps} />);
    expect(screen.getByLabelText(/Tags/i)).toBeTruthy();
  });

  it("renders description field", () => {
    renderWithProviders(<ToolAdvancedSettings {...defaultProps} />);
    expect(screen.getByLabelText(/Description/i)).toBeTruthy();
  });

  it("calls onAuthTypeChange when radio changes to basic", () => {
    const onAuthTypeChange = vi.fn();
    renderWithProviders(
      <ToolAdvancedSettings {...defaultProps} onAuthTypeChange={onAuthTypeChange} />
    );
    const basicRadio = screen.getByRole("radio", { name: /Basic/i });
    fireEvent.click(basicRadio);
    expect(onAuthTypeChange).toHaveBeenCalledWith("basic");
  });

  it("calls onAuthTypeChange when radio changes to bearer", () => {
    const onAuthTypeChange = vi.fn();
    renderWithProviders(
      <ToolAdvancedSettings {...defaultProps} onAuthTypeChange={onAuthTypeChange} />
    );
    const bearerRadio = screen.getByRole("radio", { name: /Bearer token/i });
    fireEvent.click(bearerRadio);
    expect(onAuthTypeChange).toHaveBeenCalledWith("bearer");
  });

  it("calls onAuthTypeChange when radio changes to custom", () => {
    const onAuthTypeChange = vi.fn();
    renderWithProviders(
      <ToolAdvancedSettings {...defaultProps} onAuthTypeChange={onAuthTypeChange} />
    );
    const customRadio = screen.getByRole("radio", { name: /Custom headers/i });
    fireEvent.click(customRadio);
    expect(onAuthTypeChange).toHaveBeenCalledWith("custom");
  });

  it("shows BasicAuth component when authType is basic", () => {
    renderWithProviders(
      <ToolAdvancedSettings {...defaultProps} authType="basic" basicAuthUsername="admin" />
    );
    expect(screen.getByLabelText(/Username/i)).toBeTruthy();
    expect(screen.getByLabelText(/Password/i)).toBeTruthy();
  });

  it("shows ToolBearerTokenAuth when authType is bearer", () => {
    renderWithProviders(
      <ToolAdvancedSettings {...defaultProps} authType="bearer" bearerToken="mytoken" />
    );
    const input = screen.getByPlaceholderText(/Paste bearer token/i) as HTMLInputElement;
    expect(input.value).toBe("mytoken");
  });

  it("shows CustomHeadersAuth when authType is custom", () => {
    renderWithProviders(
      <ToolAdvancedSettings {...defaultProps} authType="custom" />
    );
    expect(screen.getByRole("button", { name: /Add header/i })).toBeTruthy();
  });

  it("renders no auth content when authType is none", () => {
    renderWithProviders(
      <ToolAdvancedSettings {...defaultProps} authType="none" />
    );
    // No basic/bearer/custom fields should be visible
    expect(screen.queryByLabelText(/Username/i)).toBeNull();
    expect(screen.queryByPlaceholderText(/Paste bearer token/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /Add header/i })).toBeNull();
  });

  it("shows team hint when visibility is team and selectedTeamId is set", () => {
    renderWithProviders(
      <ToolAdvancedSettings {...defaultProps} visibility="team" />
    );
    expect(screen.getByText(/currently selected team/i)).toBeTruthy();
  });

  it("calls onResponseFilterChange when response filter changes", () => {
    const onResponseFilterChange = vi.fn();
    renderWithProviders(
      <ToolAdvancedSettings {...defaultProps} onResponseFilterChange={onResponseFilterChange} />
    );
    const input = screen.getByLabelText(/Response filter/i);
    fireEvent.change(input, { target: { value: ".results" } });
    expect(onResponseFilterChange).toHaveBeenCalledWith(".results");
  });

  it("calls onTagsChange when tags input changes", () => {
    const onTagsChange = vi.fn();
    renderWithProviders(
      <ToolAdvancedSettings {...defaultProps} onTagsChange={onTagsChange} />
    );
    const input = screen.getByLabelText(/Tags/i);
    fireEvent.change(input, { target: { value: "api,v2" } });
    expect(onTagsChange).toHaveBeenCalledWith("api,v2");
  });

  it("calls onDescriptionChange when description changes", () => {
    const onDescriptionChange = vi.fn();
    renderWithProviders(
      <ToolAdvancedSettings {...defaultProps} onDescriptionChange={onDescriptionChange} />
    );
    const input = screen.getByLabelText(/Description/i);
    fireEvent.change(input, { target: { value: "My tool" } });
    expect(onDescriptionChange).toHaveBeenCalledWith("My tool");
  });
});
