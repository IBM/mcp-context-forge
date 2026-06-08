import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "./select";

describe("Select Components", () => {
  it("renders SelectTrigger with value", () => {
    render(
      <Select defaultValue="apple">
        <SelectTrigger data-testid="trigger">
          <SelectValue placeholder="Pick a fruit" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="apple">Apple</SelectItem>
        </SelectContent>
      </Select>,
    );

    expect(screen.getByTestId("trigger")).toBeInTheDocument();
  });

  it("renders SelectTrigger with sm size", () => {
    render(
      <Select>
        <SelectTrigger size="sm" data-testid="trigger-sm">
          <SelectValue placeholder="Pick" />
        </SelectTrigger>
      </Select>,
    );

    expect(screen.getByTestId("trigger-sm")).toHaveAttribute("data-size", "sm");
  });

  it("renders SelectGroup and SelectLabel when opened", async () => {
    const user = userEvent.setup();
    render(
      <Select defaultValue="apple">
        <SelectTrigger data-testid="trigger">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            <SelectLabel>Fruits</SelectLabel>
            <SelectItem value="apple">Apple</SelectItem>
            <SelectItem value="banana">Banana</SelectItem>
          </SelectGroup>
        </SelectContent>
      </Select>,
    );

    await user.click(screen.getByTestId("trigger"));
    expect(screen.getByText("Fruits")).toBeInTheDocument();
  });

  it("renders SelectSeparator when opened", async () => {
    const user = userEvent.setup();
    render(
      <Select defaultValue="apple">
        <SelectTrigger data-testid="trigger">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="apple">Apple</SelectItem>
          <SelectSeparator data-testid="separator" />
          <SelectItem value="banana">Banana</SelectItem>
        </SelectContent>
      </Select>,
    );

    await user.click(screen.getByTestId("trigger"));
    expect(screen.getByTestId("separator")).toBeInTheDocument();
  });

  it("renders SelectItem options when opened", async () => {
    const user = userEvent.setup();
    render(
      <Select defaultValue="apple">
        <SelectTrigger data-testid="trigger">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="apple">Apple</SelectItem>
          <SelectItem value="banana">Banana</SelectItem>
        </SelectContent>
      </Select>,
    );

    await user.click(screen.getByTestId("trigger"));
    expect(screen.getByText("Banana")).toBeInTheDocument();
  });

  it("renders SelectContent with popper position when opened", async () => {
    const user = userEvent.setup();
    render(
      <Select defaultValue="a">
        <SelectTrigger data-testid="trigger">
          <SelectValue />
        </SelectTrigger>
        <SelectContent position="popper" data-testid="content-popper">
          <SelectItem value="a">A</SelectItem>
          <SelectItem value="b">B</SelectItem>
        </SelectContent>
      </Select>,
    );

    await user.click(screen.getByTestId("trigger"));
    expect(screen.getByTestId("content-popper")).toBeInTheDocument();
  });

  it("renders SelectLabel inside SelectGroup when opened", async () => {
    const user = userEvent.setup();
    render(
      <Select defaultValue="a">
        <SelectTrigger data-testid="trigger">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            <SelectLabel className="my-label-class">Category</SelectLabel>
            <SelectItem value="a">A</SelectItem>
          </SelectGroup>
        </SelectContent>
      </Select>,
    );

    await user.click(screen.getByTestId("trigger"));
    expect(screen.getByText("Category")).toBeInTheDocument();
  });

  it("renders SelectSeparator with custom className when opened", async () => {
    const user = userEvent.setup();
    render(
      <Select defaultValue="a">
        <SelectTrigger data-testid="trigger">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="a">A</SelectItem>
          <SelectSeparator className="my-sep" data-testid="styled-sep" />
          <SelectItem value="b">B</SelectItem>
        </SelectContent>
      </Select>,
    );

    await user.click(screen.getByTestId("trigger"));
    expect(screen.getByTestId("styled-sep")).toBeInTheDocument();
  });
});
