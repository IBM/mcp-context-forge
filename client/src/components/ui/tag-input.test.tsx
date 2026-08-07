import { describe, it, expect } from "vitest";
import { useState } from "react";
import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders as render } from "@/test/test-utils";
import { TagInput } from "./tag-input";

function Harness({
  initial = [],
  suggestions,
  maxTags,
  disabled,
}: {
  initial?: string[];
  suggestions?: string[];
  maxTags?: number;
  disabled?: boolean;
}) {
  const [value, setValue] = useState<string[]>(initial);
  return (
    <TagInput
      value={value}
      onChange={setValue}
      suggestions={suggestions}
      maxTags={maxTags}
      disabled={disabled}
      placeholder="add tags"
    />
  );
}

describe("TagInput", () => {
  it("renders existing tags as removable chips", () => {
    render(<Harness initial={["auth", "api"]} />);
    expect(screen.getByText("auth")).toBeInTheDocument();
    expect(screen.getByText("api")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove auth" })).toBeInTheDocument();
  });

  it("commits a tag on Enter", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByRole("combobox"), "greeting{Enter}");
    expect(screen.getByText("greeting")).toBeInTheDocument();
    expect(screen.getByRole("combobox")).toHaveValue("");
  });

  it("commits a tag when a comma is typed", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByRole("combobox"), "one,");
    expect(screen.getByText("one")).toBeInTheDocument();
  });

  it("removes the last tag on Backspace when the input is empty", async () => {
    const user = userEvent.setup();
    render(<Harness initial={["one", "two"]} />);
    await user.click(screen.getByRole("combobox"));
    await user.keyboard("{Backspace}");
    expect(screen.queryByText("two")).not.toBeInTheDocument();
    expect(screen.getByText("one")).toBeInTheDocument();
  });

  it("removes a tag via its X button", async () => {
    const user = userEvent.setup();
    render(<Harness initial={["one", "two"]} />);
    await user.click(screen.getByRole("button", { name: "Remove one" }));
    expect(screen.queryByText("one")).not.toBeInTheDocument();
    expect(screen.getByText("two")).toBeInTheDocument();
  });

  it("splits a pasted delimited list into multiple tags", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("combobox"));
    await user.paste("a, b\tc");
    expect(screen.getByText("a")).toBeInTheDocument();
    expect(screen.getByText("b")).toBeInTheDocument();
    expect(screen.getByText("c")).toBeInTheDocument();
  });

  it("dedupes case-insensitively", async () => {
    const user = userEvent.setup();
    render(<Harness initial={["auth"]} />);
    await user.type(screen.getByRole("combobox"), "AUTH{Enter}");
    expect(screen.getAllByText(/auth/i)).toHaveLength(1);
  });

  it("shows matching suggestions and adds one on click", async () => {
    const user = userEvent.setup();
    render(<Harness suggestions={["production", "profiling", "staging"]} />);
    await user.type(screen.getByRole("combobox"), "pro");
    const listbox = await screen.findByRole("listbox");
    await user.click(within(listbox).getByText("production"));
    expect(screen.getByText("production")).toBeInTheDocument();
  });

  it("offers a Create option for an unmatched value", async () => {
    const user = userEvent.setup();
    render(<Harness suggestions={["production"]} />);
    await user.type(screen.getByRole("combobox"), "brandnew");
    expect(await screen.findByText('Create "brandnew"')).toBeInTheDocument();
  });

  it("stops accepting tags and shows a message once maxTags is reached", () => {
    render(<Harness initial={["a", "b"]} maxTags={2} />);
    expect(screen.getByRole("combobox")).toBeDisabled();
    expect(screen.getByText("Maximum 2 tags reached.")).toBeInTheDocument();
  });

  it("restores focus to the input after removing a chip at maxTags", async () => {
    const user = userEvent.setup();
    render(<Harness initial={["only"]} maxTags={1} />);
    await user.click(screen.getByRole("button", { name: "Remove only" }));
    expect(screen.getByRole("combobox")).toBeEnabled();
    expect(screen.getByRole("combobox")).toHaveFocus();
  });

  it("disables interaction when disabled", () => {
    render(<Harness initial={["a"]} disabled />);
    expect(screen.getByRole("combobox")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove a" })).toBeDisabled();
  });

  it("selects the highlighted suggestion with ArrowDown then Enter", async () => {
    const user = userEvent.setup();
    render(<Harness suggestions={["production", "profiling"]} />);
    await user.type(screen.getByRole("combobox"), "pro");
    await screen.findByRole("listbox");
    await user.keyboard("{ArrowDown}{Enter}");
    expect(screen.getByText("production")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove production" })).toBeInTheDocument();
  });

  it("commits pending text as a chip on Tab", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByRole("combobox"), "drafted");
    await user.keyboard("{Tab}");
    expect(screen.getByRole("button", { name: "Remove drafted" })).toBeInTheDocument();
    expect(screen.getByRole("combobox")).toHaveValue("");
  });

  it("commits pending text as a chip on blur", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByRole("combobox"), "abandoned");
    await user.click(document.body);
    expect(screen.getByRole("button", { name: "Remove abandoned" })).toBeInTheDocument();
  });

  it("caps a paste at the remaining maxTags capacity and shows the max message", async () => {
    const user = userEvent.setup();
    render(<Harness maxTags={2} />);
    await user.click(screen.getByRole("combobox"));
    await user.paste("a, b, c");
    expect(screen.getByRole("button", { name: "Remove a" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove b" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove c" })).not.toBeInTheDocument();
    expect(screen.getByText("Maximum 2 tags reached.")).toBeInTheDocument();
  });

  it("splits a programmatically filled value on blur", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const input = screen.getByRole("combobox");
    await user.click(input);
    fireEvent.change(input, { target: { value: "security, qa" } });
    await user.click(document.body);
    expect(screen.getByRole("button", { name: "Remove security" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove qa" })).toBeInTheDocument();
  });
});
