import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { CustomHeadersAuth, type CustomHeader } from "./CustomHeadersAuth";

const makeHeader = (overrides: Partial<CustomHeader> = {}): CustomHeader => ({
  id: crypto.randomUUID(),
  key: "",
  value: "",
  ...overrides,
});

describe("CustomHeadersAuth", () => {
  it("renders 'one or more' description without maxHeaders", () => {
    render(<CustomHeadersAuth headers={[]} onHeadersChange={vi.fn()} />);
    expect(screen.getByText(/one or more custom headers/i)).toBeTruthy();
  });

  it("renders 'one custom header' description when maxHeaders=1", () => {
    render(<CustomHeadersAuth headers={[]} onHeadersChange={vi.fn()} maxHeaders={1} />);
    expect(screen.getByText(/one custom header with every request/i)).toBeTruthy();
  });

  it("renders Add header button", () => {
    render(<CustomHeadersAuth headers={[]} onHeadersChange={vi.fn()} />);
    expect(screen.getByRole("button", { name: /Add header/i })).toBeTruthy();
  });

  it("calls onHeadersChange with a new header when Add header is clicked", () => {
    const onHeadersChange = vi.fn();
    render(<CustomHeadersAuth headers={[]} onHeadersChange={onHeadersChange} />);
    fireEvent.click(screen.getByRole("button", { name: /Add header/i }));
    expect(onHeadersChange).toHaveBeenCalledWith([expect.objectContaining({ key: "", value: "" })]);
  });

  it("renders existing header fields", () => {
    const headers = [makeHeader({ key: "X-Api-Key", value: "secret" })]; // pragma: allowlist secret
    render(<CustomHeadersAuth headers={headers} onHeadersChange={vi.fn()} />);
    const keyInput = screen.getByLabelText(/Header key/i) as HTMLInputElement;
    expect(keyInput.value).toBe("X-Api-Key");
  });

  it("calls onHeadersChange with updated key when header key changes", () => {
    const onHeadersChange = vi.fn();
    const headers = [makeHeader({ id: "h1" })];
    render(<CustomHeadersAuth headers={headers} onHeadersChange={onHeadersChange} />);
    const keyInput = screen.getByLabelText(/Header key/i);
    fireEvent.change(keyInput, { target: { value: "Authorization" } });
    expect(onHeadersChange).toHaveBeenCalledWith([expect.objectContaining({ key: "Authorization" })]);
  });

  it("calls onHeadersChange with updated value when header value changes", () => {
    const onHeadersChange = vi.fn();
    const headers = [makeHeader({ id: "h1" })];
    render(<CustomHeadersAuth headers={headers} onHeadersChange={onHeadersChange} />);
    const valueInput = screen.getByLabelText(/^Value/i);
    fireEvent.change(valueInput, { target: { value: "Bearer token123" } });
    expect(onHeadersChange).toHaveBeenCalledWith([expect.objectContaining({ value: "Bearer token123" })]);
  });

  it("calls onHeadersChange removing header when Remove is clicked", () => {
    const onHeadersChange = vi.fn();
    const headers = [makeHeader({ id: "h1" }), makeHeader({ id: "h2" })];
    render(<CustomHeadersAuth headers={headers} onHeadersChange={onHeadersChange} />);
    const removeButtons = screen.getAllByRole("button", { name: /Remove/i });
    fireEvent.click(removeButtons[0]);
    expect(onHeadersChange).toHaveBeenCalledWith([expect.objectContaining({ id: "h2" })]);
  });

  it("disables Add header button when at maxHeaders limit", () => {
    const headers = [makeHeader({ id: "h1" })];
    render(<CustomHeadersAuth headers={headers} onHeadersChange={vi.fn()} maxHeaders={1} />);
    const addBtn = screen.getByRole("button", { name: /Add header/i }) as HTMLButtonElement;
    expect(addBtn.disabled).toBe(true);
  });

  it("enables Add header button when under maxHeaders limit", () => {
    render(<CustomHeadersAuth headers={[]} onHeadersChange={vi.fn()} maxHeaders={3} />);
    const addBtn = screen.getByRole("button", { name: /Add header/i }) as HTMLButtonElement;
    expect(addBtn.disabled).toBe(false);
  });

  it("shows default placeholder when single header", () => {
    const headers = [makeHeader({ id: "h1" })];
    render(<CustomHeadersAuth headers={headers} onHeadersChange={vi.fn()} />);
    expect(screen.getByPlaceholderText(/e\.g\. X-API-Key/i)).toBeTruthy();
  });

  it("shows generic placeholder when multiple headers", () => {
    const headers = [makeHeader({ id: "h1" }), makeHeader({ id: "h2" })];
    render(<CustomHeadersAuth headers={headers} onHeadersChange={vi.fn()} />);
    const keyInputs = screen.getAllByLabelText(/Header key/i);
    expect(keyInputs.length).toBe(2);
  });

  it("value input is type password", () => {
    const headers = [makeHeader({ id: "h1" })];
    render(<CustomHeadersAuth headers={headers} onHeadersChange={vi.fn()} />);
    const valueInput = screen.getByPlaceholderText(/Add header value/i) as HTMLInputElement;
    expect(valueInput.type).toBe("password");
  });

  it("handles multiple headers being rendered", () => {
    const headers = [
      makeHeader({ id: "h1", key: "Key1", value: "Val1" }),
      makeHeader({ id: "h2", key: "Key2", value: "Val2" }),
    ];
    render(<CustomHeadersAuth headers={headers} onHeadersChange={vi.fn()} />);
    const removeButtons = screen.getAllByRole("button", { name: /Remove/i });
    expect(removeButtons.length).toBe(2);
  });
});
