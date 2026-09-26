import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Shimmer, Spinner } from "./Indicators";

describe("Spinner", () => {
  it("is a decorative, CSS-tokenised indicator", () => {
    const { container } = render(<Spinner />);
    const spinner = container.querySelector("svg");

    expect(spinner).toHaveAttribute("aria-hidden", "true");
    expect(spinner).toHaveClass("feedback-spinner");
    expect(spinner).not.toHaveAttribute("style");
  });
});

describe("Shimmer", () => {
  it("exposes its text without hiding it or imposing a live-region role", () => {
    render(<Shimmer data-testid="shimmer">產生中</Shimmer>);
    const shimmer = screen.getByTestId("shimmer");

    expect(shimmer).toHaveClass("status-shimmer");
    expect(shimmer).toHaveTextContent("產生中");
    expect(shimmer).not.toHaveAttribute("aria-hidden");
    expect(shimmer).not.toHaveAttribute("role");
    expect(shimmer).not.toHaveAttribute("style");
  });
});
