import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { ListSearch } from "./list-search";

function Harness({ initial = "" }: { initial?: string }) {
  const [value, setValue] = useState(initial);
  return (
    <ListSearch value={value} onChange={setValue} ariaLabel="Search users" placeholder="Search" />
  );
}

describe("ListSearch", () => {
  it("renders an accessible search trigger and input", () => {
    render(<Harness />);
    expect(screen.getByRole("button", { name: "Search users" })).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Search users" })).toBeInTheDocument();
  });

  it("updates the value as the user types", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const input = screen.getByRole("searchbox", { name: "Search users" });
    await user.type(input, "alice");
    expect(input).toHaveValue("alice");
  });

  it("focuses the input when the trigger is clicked", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Search users" }));
    expect(screen.getByRole("searchbox", { name: "Search users" })).toHaveFocus();
  });
});
