import { describe, it, expect, vi } from "vitest";
import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Combobox, type ComboboxOption } from "./combobox";

const OPTIONS: ComboboxOption[] = [
  { value: "alice@example.com", label: "Alice (alice@example.com)", searchText: "Alice" },
  { value: "bob@example.com", label: "Bob (bob@example.com)", searchText: "Bob" },
  { value: "carol@example.com", label: "Carol (carol@example.com)", searchText: "Carol" },
];

describe("Combobox", () => {
  it("exposes combobox ARIA semantics on the input", () => {
    render(<Combobox options={OPTIONS} />);
    const input = screen.getByRole("combobox");
    expect(input).toHaveAttribute("aria-expanded", "false");
    expect(input).toHaveAttribute("aria-autocomplete", "list");
  });

  it("opens a listbox of options on focus and marks the active option", async () => {
    const user = userEvent.setup();
    render(<Combobox options={OPTIONS} />);

    await user.click(screen.getByRole("combobox"));

    const listbox = screen.getByRole("listbox");
    expect(screen.getByRole("combobox")).toHaveAttribute("aria-expanded", "true");
    expect(within(listbox).getAllByRole("option")).toHaveLength(3);
    // First entry is active by default and wired via aria-activedescendant.
    const active = screen.getByRole("combobox").getAttribute("aria-activedescendant");
    expect(active).toBeTruthy();
    expect(document.getElementById(active!)).toHaveTextContent("Alice");
  });

  it("navigates options with arrow keys and selects with Enter", async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    render(<Combobox options={OPTIONS} onValueChange={onValueChange} />);

    await user.click(screen.getByRole("combobox"));
    await user.keyboard("{ArrowDown}{ArrowDown}{Enter}"); // Alice -> Bob -> Carol

    expect(onValueChange).toHaveBeenCalledWith("carol@example.com");
    // Listbox closes after selection.
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("wraps around when navigating past the last option", async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    render(<Combobox options={OPTIONS} onValueChange={onValueChange} />);

    await user.click(screen.getByRole("combobox"));
    await user.keyboard("{ArrowUp}{Enter}"); // wraps from first to last

    expect(onValueChange).toHaveBeenCalledWith("carol@example.com");
  });

  it("filters options by search text", async () => {
    const user = userEvent.setup();
    render(<Combobox options={OPTIONS} allowCustomValue={false} />);

    await user.click(screen.getByRole("combobox"));
    await user.keyboard("bob");

    const options = within(screen.getByRole("listbox")).getAllByRole("option");
    expect(options).toHaveLength(1);
    expect(options[0]).toHaveTextContent("Bob");
  });

  it("selects an option on click", async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    render(<Combobox options={OPTIONS} onValueChange={onValueChange} />);

    await user.click(screen.getByRole("combobox"));
    await user.click(screen.getByRole("option", { name: /Bob/ }));

    expect(onValueChange).toHaveBeenCalledWith("bob@example.com");
  });

  it("offers a custom value when allowCustomValue is true", async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    render(<Combobox options={OPTIONS} onValueChange={onValueChange} allowCustomValue />);

    await user.click(screen.getByRole("combobox"));
    await user.keyboard("new@example.com");
    await user.keyboard("{ArrowDown}{Enter}"); // move onto the custom entry and commit

    expect(onValueChange).toHaveBeenCalledWith("new@example.com");
  });

  it("shows the empty text and no custom entry when allowCustomValue is false", async () => {
    const user = userEvent.setup();
    render(<Combobox options={OPTIONS} allowCustomValue={false} emptyText="No user found." />);

    await user.click(screen.getByRole("combobox"));
    await user.keyboard("zzz");

    expect(screen.getByText("No user found.")).toBeInTheDocument();
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
  });

  it("jumps to the last option with End and back to the first with Home", async () => {
    const user = userEvent.setup();
    render(<Combobox options={OPTIONS} allowCustomValue={false} />);

    await user.click(screen.getByRole("combobox"));
    await user.keyboard("{End}");
    let active = screen.getByRole("combobox").getAttribute("aria-activedescendant");
    expect(document.getElementById(active!)).toHaveTextContent("Carol");

    await user.keyboard("{Home}");
    active = screen.getByRole("combobox").getAttribute("aria-activedescendant");
    expect(document.getElementById(active!)).toHaveTextContent("Alice");
  });

  it("closes when focus leaves the component", async () => {
    const user = userEvent.setup();
    render(
      <>
        <Combobox options={OPTIONS} />
        <button type="button">outside</button>
      </>,
    );

    await user.click(screen.getByRole("combobox"));
    expect(screen.getByRole("listbox")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "outside" }));
    await waitFor(() => expect(screen.queryByRole("listbox")).not.toBeInTheDocument());
  });

  it("closes on Escape without selecting", async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    render(<Combobox options={OPTIONS} onValueChange={onValueChange} />);

    await user.click(screen.getByRole("combobox"));
    expect(screen.getByRole("listbox")).toBeInTheDocument();

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(onValueChange).not.toHaveBeenCalled();
  });

  it("does not open when disabled", async () => {
    const user = userEvent.setup();
    render(<Combobox options={OPTIONS} disabled />);

    await user.click(screen.getByRole("combobox"));

    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("shows the selected option's label when closed", () => {
    render(<Combobox options={OPTIONS} value="bob@example.com" />);
    expect(screen.getByRole("combobox")).toHaveValue("Bob (bob@example.com)");
  });
});
