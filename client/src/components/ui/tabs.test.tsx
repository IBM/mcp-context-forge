import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "./tabs";

function Fixture({ defaultValue = "one" }: { defaultValue?: string }) {
  return (
    <Tabs defaultValue={defaultValue}>
      <TabsList>
        <TabsTrigger value="one">One</TabsTrigger>
        <TabsTrigger value="two">Two</TabsTrigger>
      </TabsList>
      <TabsContent value="one">first panel</TabsContent>
      <TabsContent value="two">second panel</TabsContent>
    </Tabs>
  );
}

describe("Tabs", () => {
  it("renders the default panel and hides the inactive one", () => {
    render(<Fixture />);
    expect(screen.getByText("first panel")).toBeInTheDocument();
    expect(screen.queryByText("second panel")).not.toBeInTheDocument();
  });

  it("switches panels when a trigger is clicked", async () => {
    const user = userEvent.setup();
    render(<Fixture />);
    await user.click(screen.getByRole("tab", { name: "Two" }));
    expect(screen.getByText("second panel")).toBeInTheDocument();
    expect(screen.queryByText("first panel")).not.toBeInTheDocument();
  });

  it("supports keyboard navigation between triggers", async () => {
    const user = userEvent.setup();
    render(<Fixture />);
    const first = screen.getByRole("tab", { name: "One" });
    first.focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Two" })).toHaveFocus();
  });

  it("marks the active trigger with data-state=active", () => {
    render(<Fixture defaultValue="two" />);
    expect(screen.getByRole("tab", { name: "Two" })).toHaveAttribute("data-state", "active");
    expect(screen.getByRole("tab", { name: "One" })).toHaveAttribute("data-state", "inactive");
  });

  it("applies line-variant classes to the list", () => {
    render(
      <Tabs defaultValue="one">
        <TabsList variant="line">
          <TabsTrigger variant="line" value="one">
            One
          </TabsTrigger>
        </TabsList>
        <TabsContent value="one">first panel</TabsContent>
      </Tabs>,
    );
    const list = screen.getByRole("tablist");
    expect(list).toHaveClass("border-b");
    expect(list).toHaveClass("w-full");
  });

  it("applies line-variant classes to the trigger", () => {
    render(
      <Tabs defaultValue="one">
        <TabsList variant="line">
          <TabsTrigger variant="line" value="one">
            One
          </TabsTrigger>
        </TabsList>
        <TabsContent value="one">first panel</TabsContent>
      </Tabs>,
    );
    const trigger = screen.getByRole("tab", { name: "One" });
    expect(trigger).toHaveClass("border-b-2");
    expect(trigger).toHaveClass("data-[state=active]:border-foreground");
  });
});
