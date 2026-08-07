import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { useState } from "react";

import { useElementWidth } from "./useElementWidth";

// jsdom reports clientWidth as 0; stub it so the hook has a width to read.
let clientWidthSpy: PropertyDescriptor | undefined;
beforeAll(() => {
  clientWidthSpy = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientWidth");
  Object.defineProperty(HTMLElement.prototype, "clientWidth", {
    configurable: true,
    get() {
      return 800;
    },
  });
});
afterAll(() => {
  if (clientWidthSpy) {
    Object.defineProperty(HTMLElement.prototype, "clientWidth", clientWidthSpy);
  }
});

function Probe() {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const [mounted, setMounted] = useState(false);
  return (
    <div>
      <span data-testid="width">{width}</span>
      <button onClick={() => setMounted(true)}>mount</button>
      {mounted && <div ref={ref}>box</div>}
    </div>
  );
}

describe("useElementWidth", () => {
  it("measures the element when it mounts after the first render", () => {
    render(<Probe />);

    // The measured element is not in the tree yet (mirrors McpHealthCard's
    // loading/empty early-returns), so width starts at 0.
    expect(screen.getByTestId("width").textContent).toBe("0");

    // Mounting the element later must still trigger a measurement — the bug this
    // guards against is a one-shot effect that never re-runs for a late mount.
    act(() => {
      screen.getByRole("button").click();
    });

    expect(screen.getByTestId("width").textContent).toBe("800");
  });
});
