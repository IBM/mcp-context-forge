import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardAction,
  CardContent,
  CardFooter,
} from "./card";

describe("Card Components", () => {
  it("renders Card with default size", () => {
    render(<Card data-testid="card">Content</Card>);
    const card = screen.getByTestId("card");
    expect(card).toBeInTheDocument();
    expect(card).toHaveAttribute("data-size", "default");
  });

  it("renders Card with sm size", () => {
    render(
      <Card size="sm" data-testid="card-sm">
        Content
      </Card>,
    );
    expect(screen.getByTestId("card-sm")).toHaveAttribute("data-size", "sm");
  });

  it("renders CardHeader", () => {
    render(<CardHeader data-testid="header">Header</CardHeader>);
    expect(screen.getByTestId("header")).toBeInTheDocument();
  });

  it("renders CardTitle", () => {
    render(<CardTitle data-testid="title">Title</CardTitle>);
    expect(screen.getByTestId("title")).toHaveTextContent("Title");
  });

  it("renders CardDescription", () => {
    render(<CardDescription data-testid="desc">Description</CardDescription>);
    expect(screen.getByTestId("desc")).toHaveTextContent("Description");
  });

  it("renders CardAction", () => {
    render(
      <CardAction data-testid="action">
        <button>Click</button>
      </CardAction>,
    );
    expect(screen.getByTestId("action")).toBeInTheDocument();
  });

  it("renders CardContent", () => {
    render(<CardContent data-testid="content">Body</CardContent>);
    expect(screen.getByTestId("content")).toHaveTextContent("Body");
  });

  it("renders CardFooter", () => {
    render(<CardFooter data-testid="footer">Footer</CardFooter>);
    expect(screen.getByTestId("footer")).toHaveTextContent("Footer");
  });

  it("renders full card composition", () => {
    render(
      <Card data-testid="full-card">
        <CardHeader>
          <CardTitle>My Card</CardTitle>
          <CardDescription>A description</CardDescription>
          <CardAction data-testid="card-action-btn">
            <button>Edit</button>
          </CardAction>
        </CardHeader>
        <CardContent>Main content</CardContent>
        <CardFooter>Footer content</CardFooter>
      </Card>,
    );

    expect(screen.getByTestId("full-card")).toBeInTheDocument();
    expect(screen.getByTestId("card-action-btn")).toBeInTheDocument();
    expect(screen.getByText("My Card")).toBeInTheDocument();
    expect(screen.getByText("Main content")).toBeInTheDocument();
    expect(screen.getByText("Footer content")).toBeInTheDocument();
  });

  it("applies custom className to CardAction", () => {
    render(
      <CardAction className="custom-action" data-testid="styled-action">
        Action
      </CardAction>,
    );
    expect(screen.getByTestId("styled-action")).toBeInTheDocument();
  });
});
