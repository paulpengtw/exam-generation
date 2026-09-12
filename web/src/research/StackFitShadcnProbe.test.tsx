import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, afterEach, vi } from "vitest";

import { StackFitShadcnProbe } from "./StackFitShadcnProbe";

describe("shadcn Vite probe", () => {
  beforeEach(() => {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders Button and Toaster together", () => {
    render(<StackFitShadcnProbe />);

    expect(screen.getByRole("button", { name: "Shadcn probe" })).toBeInTheDocument();
  });
});
