import { describe, it, expect } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useLocalSearch } from "./useLocalSearch";

interface Row {
  id: string;
  name: string;
}

const items: Row[] = [
  { id: "1", name: "Alpha" },
  { id: "2", name: "Beta" },
];

const getText = (row: Row) => `${row.name} ${row.id}`;

describe("useLocalSearch", () => {
  it("returns all items when the query is empty", () => {
    const { result } = renderHook(() => useLocalSearch(items, getText));
    expect(result.current.results).toEqual(items);
  });

  it("filters by text once the debounce elapses", async () => {
    const { result } = renderHook(() => useLocalSearch(items, getText, 50));

    act(() => result.current.setQuery("alpha"));

    await waitFor(() => {
      expect(result.current.results).toEqual([items[0]]);
    });
  });

  it("matches on the id field", async () => {
    const { result } = renderHook(() => useLocalSearch(items, getText, 50));

    act(() => result.current.setQuery("2"));

    await waitFor(() => {
      expect(result.current.results).toEqual([items[1]]);
    });
  });
});
