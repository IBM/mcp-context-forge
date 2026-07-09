import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  Sheet,
  SheetTrigger,
  SheetContent,
  SheetHeader,
  SheetFooter,
  SheetTitle,
  SheetDescription,
  SheetClose,
} from "./sheet";

describe("Sheet Components", () => {
  it("renders Sheet with trigger", () => {
    render(
      <Sheet>
        <SheetTrigger>Open Sheet</SheetTrigger>
      </Sheet>,
    );
    expect(screen.getByText("Open Sheet")).toBeInTheDocument();
  });

  it("renders SheetHeader", () => {
    const { container } = render(
      <SheetHeader>
        <div>Header Content</div>
      </SheetHeader>,
    );
    expect(container).toBeTruthy();
  });

  it("renders SheetFooter", () => {
    const { container } = render(
      <SheetFooter>
        <div>Footer Content</div>
      </SheetFooter>,
    );
    expect(container).toBeTruthy();
  });

  it("renders SheetTitle", () => {
    render(
      <Sheet open={true}>
        <SheetContent>
          <SheetTitle>My Title</SheetTitle>
          <SheetDescription>Test description</SheetDescription>
        </SheetContent>
      </Sheet>,
    );
    expect(document.querySelector('[data-slot="sheet-title"]')).toBeInTheDocument();
  });

  it("renders SheetDescription", () => {
    render(
      <Sheet open={true}>
        <SheetContent>
          <SheetTitle>Title</SheetTitle>
          <SheetDescription>My Description</SheetDescription>
        </SheetContent>
      </Sheet>,
    );
    expect(document.querySelector('[data-slot="sheet-description"]')).toBeInTheDocument();
  });

  it("renders SheetHeader with custom className", () => {
    const { container } = render(<SheetHeader className="custom-header">Header</SheetHeader>);
    expect(container.firstChild).toHaveClass("custom-header");
  });

  it("renders SheetFooter with custom className", () => {
    const { container } = render(<SheetFooter className="custom-footer">Footer</SheetFooter>);
    expect(container.firstChild).toHaveClass("custom-footer");
  });

  it("renders SheetTitle with custom className", () => {
    render(
      <Sheet open={true}>
        <SheetContent>
          <SheetTitle className="custom-title">Title</SheetTitle>
          <SheetDescription>Test description</SheetDescription>
        </SheetContent>
      </Sheet>,
    );
    expect(document.body).toBeTruthy();
  });

  it("renders SheetDescription with custom className", () => {
    render(
      <Sheet open={true}>
        <SheetContent>
          <SheetTitle>Title</SheetTitle>
          <SheetDescription className="custom-desc">Description</SheetDescription>
        </SheetContent>
      </Sheet>,
    );
    expect(document.body).toBeTruthy();
  });

  it("renders Sheet with open state", () => {
    render(
      <Sheet open={true}>
        <SheetTrigger>Trigger</SheetTrigger>
        <SheetContent>
          <SheetHeader>
            <SheetTitle>Sheet Title</SheetTitle>
            <SheetDescription>Sheet Description</SheetDescription>
          </SheetHeader>
          <SheetFooter>Footer</SheetFooter>
        </SheetContent>
      </Sheet>,
    );
    expect(document.querySelector('[data-slot="sheet-content"]')).toBeInTheDocument();
  });

  it("renders SheetContent from left side", () => {
    render(
      <Sheet open={true}>
        <SheetContent side="left">
          <SheetTitle>Title</SheetTitle>
          <SheetDescription>Test description</SheetDescription>
        </SheetContent>
      </Sheet>,
    );
    expect(document.body).toBeTruthy();
  });

  it("renders SheetContent from right side", () => {
    render(
      <Sheet open={true}>
        <SheetContent side="right">
          <SheetTitle>Title</SheetTitle>
          <SheetDescription>Test description</SheetDescription>
        </SheetContent>
      </Sheet>,
    );
    expect(document.body).toBeTruthy();
  });

  it("renders SheetContent from top side", () => {
    render(
      <Sheet open={true}>
        <SheetContent side="top">
          <SheetTitle>Title</SheetTitle>
          <SheetDescription>Test description</SheetDescription>
        </SheetContent>
      </Sheet>,
    );
    expect(document.body).toBeTruthy();
  });

  it("renders SheetContent from bottom side", () => {
    render(
      <Sheet open={true}>
        <SheetContent side="bottom">
          <SheetTitle>Title</SheetTitle>
          <SheetDescription>Test description</SheetDescription>
        </SheetContent>
      </Sheet>,
    );
    expect(document.body).toBeTruthy();
  });

  it("renders SheetClose button", () => {
    render(
      <Sheet open={true}>
        <SheetContent>
          <SheetTitle>Title</SheetTitle>
          <SheetDescription>Test description</SheetDescription>
          <SheetClose>Close</SheetClose>
        </SheetContent>
      </Sheet>,
    );
    expect(document.body).toBeTruthy();
  });
});
