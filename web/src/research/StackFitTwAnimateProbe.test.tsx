import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StackFitTwAnimateProbe } from "./StackFitTwAnimateProbe";

describe("tw-animate-css probe", () => {
  it("leaves enter classes and CSS tokens on the DOM", () => {
    render(<StackFitTwAnimateProbe />);
    const element = screen.getByTestId("tw-animate-probe");

    expect(element).toHaveClass("animate-in", "fade-in", "slide-in-from-bottom-2");
    expect(element.style.getPropertyValue("--motion-duration")).toBe("200ms");
    expect(getComputedStyle(element).animationName).toBe("none");
  });
});
