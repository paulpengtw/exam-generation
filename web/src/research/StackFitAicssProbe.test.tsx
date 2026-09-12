import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ThinkingState } from "../ThinkingState";

describe("AICSS registry probe", () => {
  it("renders the registry component in jsdom", () => {
    render(<ThinkingState />);

    expect(screen.getByText("Thinking")).toBeInTheDocument();
  });
});
