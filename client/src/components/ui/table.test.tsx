import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  Table,
  TableHeader,
  TableBody,
  TableFooter,
  TableRow,
  TableHead,
  TableCell,
  TableCaption,
} from "./table";

describe("Table Components", () => {
  it("renders a full table composition including TableFooter", () => {
    render(
      <Table data-testid="table">
        <TableCaption data-testid="caption">A list of items</TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Value</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow>
            <TableCell>Item A</TableCell>
            <TableCell>100</TableCell>
          </TableRow>
        </TableBody>
        <TableFooter data-testid="footer">
          <TableRow>
            <TableCell>Total</TableCell>
            <TableCell>100</TableCell>
          </TableRow>
        </TableFooter>
      </Table>,
    );

    expect(screen.getByTestId("table")).toBeInTheDocument();
    expect(screen.getByTestId("caption")).toHaveTextContent("A list of items");
    expect(screen.getByTestId("footer")).toBeInTheDocument();
    expect(screen.getByText("Total")).toBeInTheDocument();
  });

  it("renders TableFooter with custom className", () => {
    render(
      <table>
        <TableFooter className="custom-footer" data-testid="styled-footer">
          <tr>
            <td>Footer content</td>
          </tr>
        </TableFooter>
      </table>,
    );

    expect(screen.getByTestId("styled-footer")).toBeInTheDocument();
  });
});
